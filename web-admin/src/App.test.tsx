/**
 * The admin panel with tabs for Build Types, Agents, and Models.
 *
 * M2 adds three features:
 * - Tab switching: each tab pane renders its content
 * - Agents tab: edit admin-configured prompts for five agent roles
 * - Models tab: CRUD the model catalog of base ids
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listBuildTypes = vi.fn()
const createBuildType = vi.fn()
const updateBuildType = vi.fn()
const removeBuildType = vi.fn()
const listBusinessModels = vi.fn()
const createBusinessModel = vi.fn()
const updateBusinessModel = vi.fn()
const removeBusinessModel = vi.fn()
const listChatAgents = vi.fn()
const getBuiltinAgents = vi.fn()
const createChatAgent = vi.fn()
const updateChatAgent = vi.fn()
const deleteChatAgent = vi.fn()
const listModelCatalog = vi.fn()
const createModelCatalogEntry = vi.fn()
const updateModelCatalogEntry = vi.fn()
const deleteModelCatalogEntry = vi.fn()
const getModelSelection = vi.fn()
const setModelSelection = vi.fn()

const getFreshIdToken = vi.fn(() => Promise.resolve('test-token'))

vi.mock('./lib/auth', () => ({
  getCurrentSession: () =>
    Promise.resolve({ getIdToken: () => ({ getJwtToken: () => 'test-token' }) }),
  getFreshIdToken,
}))

const createApiCalls: Array<() => string | null | Promise<string | null>> = []

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    createApi: (getIdToken: () => string | null | Promise<string | null>) => {
      createApiCalls.push(getIdToken)
      return {
      list: listBuildTypes,
      create: createBuildType,
      update: updateBuildType,
      remove: removeBuildType,
      listBusinessModels,
      createBusinessModel,
      updateBusinessModel,
      removeBusinessModel,
      listChatAgents,
      getBuiltinAgents,
      createChatAgent,
      updateChatAgent,
      deleteChatAgent,
      listModelCatalog,
      createModelCatalogEntry,
      updateModelCatalogEntry,
      deleteModelCatalogEntry,
      getModelSelection,
      setModelSelection,
      }
    },
  }
})

const { default: App } = await import('./App')

const MICRO_SAAS = {
  id: 'bt1',
  key: 'micro-saas',
  label: 'MicroSaaS',
  description: 'One narrow job.',
  active: true,
  sort_order: 1,
}

const RESEARCH_AGENT = {
  agent_key: 'idea-scout-community',
  agent_name: 'idea-scout-community',
  role: 'idea-scout-community',
  system_prompt: 'Research communities...',
  model: 'anthropic/claude-sonnet-4',
  required_group: 'founder',
  active: true,
  max_history_messages: 10,
  max_output_tokens: 2000,
  timeout_seconds: 30,
}

const SYNTHESIS_AGENT = {
  agent_key: 'idea-scout-synthesis',
  agent_name: 'idea-scout-synthesis',
  role: 'idea-scout-synthesis',
  system_prompt: 'Synthesize findings...',
  model: 'anthropic/claude-opus-4-8',
  required_group: 'founder',
  active: true,
  max_history_messages: 10,
  max_output_tokens: 2000,
  timeout_seconds: 30,
}

const BUILTIN_COMMUNITY_AGENT = {
  agent_key: 'idea-scout-community',
  agent_name: 'idea-scout-community',
  role: 'idea-scout-community',
  system_prompt:
    'You are Idea Scout\'s community-signal researcher. Your angle is what people are actually complaining about, asking for, and hacking around in public — forums, Q&A sites, review threads, discussion boards, issue trackers, subreddits.',
  model: 'anthropic/claude-sonnet-4',
  required_group: 'founder',
  active: true,
  max_history_messages: 10,
  max_output_tokens: 2000,
  timeout_seconds: 30,
}

const BUILTIN_NARRATIVE_AGENT = {
  agent_key: 'idea-scout-narrative',
  agent_name: 'idea-scout-narrative',
  role: 'idea-scout-narrative',
  system_prompt:
    'You are Idea Scout\'s narrative researcher. Your angle is what operators and founders say is changing in markets.',
  model: 'anthropic/claude-sonnet-4',
  required_group: 'founder',
  active: true,
  max_history_messages: 10,
  max_output_tokens: 2000,
  timeout_seconds: 30,
}

const BUILTIN_COMPETITIVE_AGENT = {
  agent_key: 'idea-scout-competitive',
  agent_name: 'idea-scout-competitive',
  role: 'idea-scout-competitive',
  system_prompt: 'You are Idea Scout\'s competitive researcher. Your angle is gaps and weaknesses.',
  model: 'anthropic/claude-sonnet-4',
  required_group: 'founder',
  active: true,
  max_history_messages: 10,
  max_output_tokens: 2000,
  timeout_seconds: 30,
}

const BUILTIN_SYNTHESIS_AGENT = {
  agent_key: 'idea-scout-synthesis',
  agent_name: 'idea-scout-synthesis',
  role: 'idea-scout-synthesis',
  system_prompt: 'You are Idea Scout\'s synthesis agent. Reconcile three research angles.',
  model: 'anthropic/claude-opus-4-8',
  required_group: 'founder',
  active: true,
  max_history_messages: 10,
  max_output_tokens: 2000,
  timeout_seconds: 30,
}

const MODEL_WEB_CAPABLE = {
  id: 'model1',
  model_id: 'anthropic/claude-opus',
  label: 'Claude Opus (Web)',
  active: true,
  is_default: true,
}

const MODEL_NOT_WEB_CAPABLE = {
  id: 'model2',
  model_id: 'anthropic/claude-opus',
  label: 'Claude Opus (No Web)',
  active: true,
  is_default: false,
}

const AGENT_KEYS: Array<[string, boolean]> = [
  ['idea-scout-community', true],
  ['idea-scout-narrative', true],
  ['idea-scout-competitive', true],
  ['idea-scout-synthesis', false],
  ['idea-scout-candidate-writer', false],
  ['idea-scout-prd-interviewer', false],
  ['idea-scout-prd-writer', false],
]

function selectionFor(base: string, drift: string[] = []) {
  return {
    selected_model_id: base,
    options: [
      { id: 'model1', model_id: 'anthropic/claude-opus', label: 'Claude Opus' },
      { id: 'model2', model_id: 'moonshotai/kimi-k3', label: 'Kimi K3 (open-weight)' },
    ],
    agents: AGENT_KEYS.map(([agent_key, web]) => ({
      agent_key,
      effective_model: web ? `${base}:online` : base,
      stored_model: drift.includes(agent_key) ? 'hand/entered:online' : web ? `${base}:online` : base,
      web_search: web,
      stored: true,
      drift: drift.includes(agent_key),
    })),
  }
}

describe('Idea Scout admin panel', () => {
  beforeEach(() => {
    window.location.hash = ''
    createApiCalls.length = 0
    getFreshIdToken.mockReset().mockResolvedValue('test-token')
    listBuildTypes.mockReset().mockResolvedValue([MICRO_SAAS])
    createBuildType.mockReset().mockResolvedValue(MICRO_SAAS)
    updateBuildType.mockReset().mockResolvedValue(MICRO_SAAS)
    removeBuildType.mockReset()
    listBusinessModels.mockReset().mockResolvedValue([])
    createBusinessModel.mockReset()
    updateBusinessModel.mockReset()
    removeBusinessModel.mockReset()
    listChatAgents.mockReset().mockResolvedValue([RESEARCH_AGENT, SYNTHESIS_AGENT])
    getBuiltinAgents.mockReset().mockResolvedValue({
      agents: [BUILTIN_COMMUNITY_AGENT, BUILTIN_NARRATIVE_AGENT, BUILTIN_COMPETITIVE_AGENT, BUILTIN_SYNTHESIS_AGENT],
    })
    createChatAgent.mockReset().mockResolvedValue(RESEARCH_AGENT)
    updateChatAgent.mockReset().mockResolvedValue(RESEARCH_AGENT)
    deleteChatAgent.mockReset()
    listModelCatalog.mockReset().mockResolvedValue([MODEL_WEB_CAPABLE, MODEL_NOT_WEB_CAPABLE])
    getModelSelection.mockReset().mockResolvedValue(selectionFor('anthropic/claude-opus'))
    setModelSelection.mockReset()
    createModelCatalogEntry.mockReset().mockResolvedValue(MODEL_WEB_CAPABLE)
    updateModelCatalogEntry.mockReset().mockResolvedValue(MODEL_WEB_CAPABLE)
    deleteModelCatalogEntry.mockReset()
  })

  describe('Business Models tab', () => {
    const SUBSCRIPTION = {
      id: 'bm1',
      key: 'subscription',
      label: 'Subscription / SaaS',
      description: 'Recurring payment for continued access.',
      active: true,
      sort_order: 1,
    }

    it('lists the models an admin has configured', async () => {
      listBusinessModels.mockResolvedValue([SUBSCRIPTION])
      render(<App />)
      await userEvent.click(await screen.findByRole('tab', { name: /^Business Models$/i }))
      expect(await screen.findByText('Subscription / SaaS')).toBeTruthy()
    })

    it('says an empty list degrades the run form rather than blocking it', async () => {
      // The consequence genuinely differs from build types, where an empty table
      // stops every run. Saying the wrong one would send an admin chasing a
      // non-problem.
      listBusinessModels.mockResolvedValue([])
      render(<App />)
      await userEvent.click(await screen.findByRole('tab', { name: /^Business Models$/i }))
      expect(await screen.findByText(/omits the picker until one exists/i)).toBeTruthy()
    })

    it('does not disturb the build-types pane it shares components with', async () => {
      listBusinessModels.mockResolvedValue([SUBSCRIPTION])
      render(<App />)
      await userEvent.click(await screen.findByRole('tab', { name: /^Business Models$/i }))
      await userEvent.click(screen.getByRole('tab', { name: /Build Types/i }))
      expect(await screen.findByText(MICRO_SAAS.label)).toBeTruthy()
      expect(screen.queryByText('Subscription / SaaS')).toBeNull()
    })
  })

  describe('Tab switching', () => {
    it('renders four tabs: Build Types, Business Models, Agents, Models', async () => {
      render(<App />)
      await waitFor(() => {
        expect(screen.getByRole('tab', { name: /Build Types/i })).toBeTruthy()
        expect(screen.getByRole('tab', { name: /^Business Models$/i })).toBeTruthy()
        expect(screen.getByRole('tab', { name: /Agents/i })).toBeTruthy()
        expect(screen.getByRole('tab', { name: /^Models$/i })).toBeTruthy()
      })
    })

    it('defaults to Build Types tab', async () => {
      render(<App />)
      await waitFor(() => {
        const buildTypesTab = screen.getByRole('tab', { name: /Build Types/i })
        expect(buildTypesTab).toHaveClass('admin-tab--active')
      })
    })

    it('exposes the selected tab via aria-selected', async () => {
      const user = userEvent.setup()
      render(<App />)
      const models = await screen.findByRole('tab', { name: /^Models$/i })
      expect(models).toHaveAttribute('aria-selected', 'false')
      await user.click(models)
      expect(models).toHaveAttribute('aria-selected', 'true')
      expect(screen.getByRole('tab', { name: /Build Types/i })).toHaveAttribute(
        'aria-selected',
        'false',
      )
    })

    it('gives each tab its own address and restores it on load', async () => {
      const user = userEvent.setup()
      const first = render(<App />)
      await user.click(await screen.findByRole('tab', { name: /Agents/i }))
      expect(window.location.hash).toBe('#/agents')
      first.unmount()

      render(<App />)
      const agents = await screen.findByRole('tab', { name: /Agents/i })
      expect(agents).toHaveAttribute('aria-selected', 'true')
    })

    it('renders the Build Types pane when Build Types tab is active', async () => {
      render(<App />)
      await waitFor(() => {
        expect(screen.getByText('MicroSaaS')).toBeTruthy()
      })
    })

    it('renders the Agents pane when Agents tab is clicked', async () => {
      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('tab', { name: /Agents/i })
      await user.click(agentsTab)

      await waitFor(() => {
        // Check for both agents by looking for multiple Edit buttons (one per agent)
        const editButtons = screen.getAllByRole('button', { name: /Edit/i })
        expect(editButtons.length).toBeGreaterThanOrEqual(2)
      })
    })

    it('renders the Models pane when Models tab is clicked', async () => {
      const user = userEvent.setup()
      render(<App />)

      const modelsTab = await screen.findByRole('tab', { name: /^Models$/i })
      await user.click(modelsTab)

      await waitFor(() => {
        expect(screen.getByText('Claude Opus (Web)')).toBeTruthy()
        expect(screen.getByText('Claude Opus (No Web)')).toBeTruthy()
      })
    })

    it('sends only changed fields, never server-managed columns, on edit save', async () => {
      const user = userEvent.setup()
      listModelCatalog.mockResolvedValue([
        {
          ...MODEL_WEB_CAPABLE,
          tenant_id: 't1',
          created_at: '2026-01-01',
          updated_at: '2026-01-02',
        },
      ])
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /^Models$/i }))
      await user.click(await screen.findByRole('button', { name: /^Edit$/i }))
      await user.click(screen.getByLabelText('Active'))
      await user.click(screen.getByRole('button', { name: /^Save$/i }))

      await waitFor(() => {
        expect(updateModelCatalogEntry).toHaveBeenCalledWith('model1', { active: false })
      })
    })

    it('clears the existing default when another model is marked default', async () => {
      const user = userEvent.setup()
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /^Models$/i }))
      expect(await screen.findByText(/Current default model: Claude Opus \(Web\)/)).toBeTruthy()
      const editButtons = await screen.findAllByRole('button', { name: /^Edit$/i })
      await user.click(editButtons[1])
      await user.click(screen.getByLabelText('Default'))
      await user.click(screen.getByRole('button', { name: /^Save$/i }))

      await waitFor(() => {
        expect(updateModelCatalogEntry).toHaveBeenCalledWith('model2', { is_default: true })
        expect(updateModelCatalogEntry).toHaveBeenCalledWith('model1', { is_default: false })
      })
    })
  })

  describe('Agents tab', () => {
    it('lists all agents with their prompts', async () => {
      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('tab', { name: /Agents/i })
      await user.click(agentsTab)

      await waitFor(() => {
        expect(screen.getByText('Research communities...')).toBeTruthy()
        // Also check for the synthesis agent's prompt
        expect(screen.getByText('Synthesize findings...')).toBeTruthy()
      })
    })

    it('allows editing an agent prompt', async () => {
      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('tab', { name: /Agents/i })
      await user.click(agentsTab)

      const editButtons = await screen.findAllByRole('button', { name: /Edit/i })
      const firstEditButton = editButtons[0]
      await user.click(firstEditButton)

      // Verify the edit form shows with the current prompt
      const textareas = screen.getAllByRole('textbox')
      const promptTextarea = textareas.find(
        (ta) => (ta as HTMLTextAreaElement).value?.includes('Research communities'),
      )
      expect(promptTextarea).toBeTruthy()

      // Edit the prompt
      await user.clear(promptTextarea as HTMLTextAreaElement)
      await user.type(promptTextarea as HTMLTextAreaElement, 'Updated prompt content')

      // Save the changes
      const saveButton = screen.getByRole('button', { name: /Save/i })
      await user.click(saveButton)

      await waitFor(() => {
        expect(updateChatAgent).toHaveBeenCalled()
      })
    })

    it('confirms the prompt edit round-trip', async () => {
      updateChatAgent.mockResolvedValue({
        ...RESEARCH_AGENT,
        system_prompt: 'Updated prompt content',
      })

      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('tab', { name: /Agents/i })
      await user.click(agentsTab)

      const editButtons = await screen.findAllByRole('button', { name: /Edit/i })
      await user.click(editButtons[0])

      const textareas = screen.getAllByRole('textbox')
      const promptTextarea = textareas.find(
        (ta) => (ta as HTMLTextAreaElement).value?.includes('Research communities'),
      )
      await user.clear(promptTextarea as HTMLTextAreaElement)
      await user.type(promptTextarea as HTMLTextAreaElement, 'Updated prompt content')

      const saveButton = screen.getByRole('button', { name: /Save/i })
      await user.click(saveButton)

      await waitFor(() => {
        expect(updateChatAgent).toHaveBeenCalled()
        const call = updateChatAgent.mock.calls[0]
        expect(call[0]).toBe('idea-scout-community')
        expect(call[1].system_prompt).toBe('Updated prompt content')
      })
    })

    it('shows no not-live-editable warning on the synthesis agent', async () => {
      // The synthesis prompt used to be frozen into the orchestration workflow's
      // action_config, so editing this row saved and changed nothing — the warning
      // existed to stop that silent no-op. Core now resolves the prompt from this
      // row at agent-run creation, so the warning would be a lie in the opposite
      // direction (biffo-template#909).
      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('tab', { name: /Agents/i })
      await user.click(agentsTab)

      // Anchor on the synthesis row actually being rendered, so this cannot pass
      // by asserting the absence of a warning on a tab that never loaded.
      await waitFor(() => {
        expect(screen.getAllByText('idea-scout-synthesis').length).toBeGreaterThan(0)
      })

      expect(screen.queryByText(/Not live-editable/i)).toBeNull()
      expect(document.querySelector('.admin-synthesis-warning')).toBeNull()
    })

    it('shows real built-in prompts, not placeholder text', async () => {
      // Start with no stored agents so built-ins display
      listChatAgents.mockResolvedValue([])

      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('tab', { name: /Agents/i })
      await user.click(agentsTab)

      await waitFor(() => {
        // Check for real prompt content from the built-in agents
        expect(
          screen.getByText(/You are Idea Scout's community-signal researcher/),
        ).toBeTruthy()
      })

      // Verify no placeholder text appears anywhere on the page
      expect(screen.queryByText(/Built-in prompt — stored row not found/)).toBeNull()
      expect(screen.queryByText(/\(Built-in default\)/)).toBeNull()
    })

    it('deletes an agent through the in-page confirm, not window.confirm', async () => {
      const nativeConfirm = vi.fn(() => true)
      vi.stubGlobal('confirm', nativeConfirm)
      const user = userEvent.setup()
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /Agents/i }))
      const [first] = await screen.findAllByRole('button', { name: 'Delete' })
      await user.click(first)
      expect(deleteChatAgent).not.toHaveBeenCalled()

      const group = await screen.findByRole('group', { name: 'Delete this agent?' })
      await user.click(within(group).getByRole('button', { name: 'Delete' }))

      await waitFor(() => expect(deleteChatAgent).toHaveBeenCalledTimes(1))
      expect(nativeConfirm).not.toHaveBeenCalled()
    })

    it('promotes a built-in with real prompt content', async () => {
      // Start with no stored agents so built-ins display
      listChatAgents.mockResolvedValue([])

      // Mock the confirmation dialog
      vi.stubGlobal('confirm', () => true)

      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('tab', { name: /Agents/i })
      await user.click(agentsTab)

      // Find the "Store a copy to edit" button for the first built-in
      const storeButtons = await screen.findAllByRole('button', {
        name: /Store a copy to edit/i,
      })
      expect(storeButtons.length).toBeGreaterThan(0)

      // Click the store button
      await user.click(storeButtons[0])

      // Verify createChatAgent was called with real prompt content
      await waitFor(() => {
        expect(createChatAgent).toHaveBeenCalled()
        const call = createChatAgent.mock.calls[0]
        expect(call[0]).toBeDefined()
        // Verify the real prompt is passed, not a placeholder
        expect(call[0].system_prompt).toContain('You are Idea Scout')
        expect(call[0].system_prompt).not.toContain('Built-in prompt — stored row not found')
      })
    })
  })

  describe('Models tab', () => {
    it('lists the catalog models', async () => {
      const user = userEvent.setup()
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /^Models$/i }))

      await waitFor(() => {
        expect(screen.getByText('Claude Opus (Web)')).toBeTruthy()
        expect(screen.getByText('Claude Opus (No Web)')).toBeTruthy()
      })
      expect(screen.queryByText(/web capable/i)).toBeNull()
    })

    it('rejects a model id containing a colon without calling the API', async () => {
      const user = userEvent.setup()
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /^Models$/i }))
      await user.click(await screen.findByRole('button', { name: /Add.*Model/i }))
      const inputs = screen.getAllByRole('textbox')
      await user.type(inputs[0], 'foo/bar:online')
      await user.type(inputs[1], 'Foo')
      expect(screen.queryByText(/web capable/i)).toBeNull()
      await user.click(screen.getByRole('button', { name: /Create/i }))

      expect(await screen.findByRole('alert')).toHaveTextContent(/cannot contain ':'/i)
      expect(createModelCatalogEntry).not.toHaveBeenCalled()
    })

    it('creates a model with a base id', async () => {
      const user = userEvent.setup()
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /^Models$/i }))
      await user.click(await screen.findByRole('button', { name: /Add.*Model/i }))
      const inputs = screen.getAllByRole('textbox')
      await user.type(inputs[0], 'anthropic/claude-3')
      await user.type(inputs[1], 'Claude 3')
      await user.click(screen.getByRole('button', { name: /Create/i }))

      await waitFor(() => {
        expect(createModelCatalogEntry).toHaveBeenCalledWith(
          expect.objectContaining({ model_id: 'anthropic/claude-3' }),
        )
      })
    })
  })

  describe('one model for every agent', () => {
    it('saves the dropdown choice with one PUT /model and shows the new effective models', async () => {
      setModelSelection.mockResolvedValue(selectionFor('moonshotai/kimi-k3'))
      const user = userEvent.setup()
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /Agents/i }))
      const select = await screen.findByRole('combobox', { name: /model for all agents/i })
      await user.selectOptions(select, 'moonshotai/kimi-k3')
      await user.click(screen.getByRole('button', { name: /apply model/i }))

      await waitFor(() => {
        expect(setModelSelection).toHaveBeenCalledTimes(1)
      })
      expect(setModelSelection).toHaveBeenCalledWith('moonshotai/kimi-k3')
      await waitFor(() => {
        expect(screen.getAllByText('moonshotai/kimi-k3:online').length).toBeGreaterThan(0)
      })
      expect(screen.getAllByText('web search: on').length).toBeGreaterThan(0)
      expect(screen.getAllByText('web search: off').length).toBeGreaterThan(0)
    })

    it('shows the error and keeps the selection when saving fails', async () => {
      setModelSelection.mockRejectedValue(new Error('422: not an active model'))
      const user = userEvent.setup()
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /Agents/i }))
      const select = (await screen.findByRole('combobox', {
        name: /model for all agents/i,
      })) as HTMLSelectElement
      await user.selectOptions(select, 'moonshotai/kimi-k3')
      await user.click(screen.getByRole('button', { name: /apply model/i }))

      expect(await screen.findByText(/not an active model/i)).toBeInTheDocument()
      await waitFor(() => expect(select.value).toBe('anthropic/claude-opus'))
    })

    it('has no model input in the agent edit form', async () => {
      const user = userEvent.setup()
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /Agents/i }))
      const editButtons = await screen.findAllByRole('button', { name: /Edit/i })
      await user.click(editButtons[0])

      expect(screen.queryByLabelText(/^Model:?$/i)).toBeNull()
      expect(screen.getByLabelText(/System Prompt/i)).toBeInTheDocument()
    })

    it('shows a drift notice whose action re-applies the selected model', async () => {
      getModelSelection.mockResolvedValue(
        selectionFor('anthropic/claude-opus', ['idea-scout-synthesis']),
      )
      setModelSelection.mockResolvedValue(selectionFor('anthropic/claude-opus'))
      const user = userEvent.setup()
      render(<App />)

      await user.click(await screen.findByRole('tab', { name: /Agents/i }))
      await user.click(await screen.findByRole('button', { name: /re-apply selected model/i }))

      await waitFor(() => {
        expect(setModelSelection).toHaveBeenCalledWith('anthropic/claude-opus')
      })
    })
  })

  describe('when the agent requests fail (#69)', () => {
    // The panel reported "No agents stored, and no built-in defaults reported"
    // while both requests were coming back 403. Two separate causes, both here.

    it('does not claim the founder has no agents when the request failed', async () => {
      listChatAgents.mockRejectedValue(new Error('403: Forbidden'))
      getBuiltinAgents.mockRejectedValue(new Error('403: Forbidden'))

      render(<App />)
      await userEvent.click(await screen.findByRole('tab', { name: /agents/i }))

      await waitFor(() => {
        expect(screen.getByText(/Could not load the agents/i)).toBeInTheDocument()
      })
      // The empty state is a claim about the founder's configuration. It must
      // not be made on the strength of a request that never succeeded.
      expect(screen.queryByText(/No agents stored/i)).not.toBeInTheDocument()
    })

    it('does not let a successful load erase another load\'s failure', async () => {
      // The four loaders fire concurrently against one shared error string, and
      // every success used to call setError(null). The models call returning 200
      // a moment after the agents call returned 403 wiped the only evidence.
      listChatAgents.mockRejectedValue(new Error('403: Forbidden'))
      getBuiltinAgents.mockRejectedValue(new Error('403: Forbidden'))
      listModelCatalog.mockResolvedValue([MODEL_WEB_CAPABLE])
      listBuildTypes.mockResolvedValue([MICRO_SAAS])

      render(<App />)

      await waitFor(() => {
        expect(screen.getByText(/Failed to load agents/i)).toBeInTheDocument()
      })
    })

    it('still says nothing is stored when the request genuinely returns none', async () => {
      // Guard the guard: the fix must not turn every empty table into an error.
      listChatAgents.mockResolvedValue([])
      getBuiltinAgents.mockResolvedValue({ agents: [] })

      render(<App />)
      await userEvent.click(await screen.findByRole('tab', { name: /agents/i }))

      await waitFor(() => {
        expect(screen.getByText(/No agents stored/i)).toBeInTheDocument()
      })
      expect(screen.queryByText(/Could not load the agents/i)).not.toBeInTheDocument()
    })
  })

  describe('token freshness (biffo-plugin-ideation#69, biffo-template#1492)', () => {
    it('wires the API client to re-resolve the token per request, not a mount-time snapshot', async () => {
      // A `CognitoUserSession` is immutable — `getIdToken()` always hands back
      // the same JWT captured at mount. `createApi(() => idToken)` froze that
      // snapshot in React state and never updated it, so once the token lapsed
      // every call 401'd for the life of the page. The fix passes `getFreshIdToken`
      // itself — which re-reads the session (and self-heals via the refresh
      // token) on every call — rather than a closure over frozen state.
      render(<App />)
      await screen.findByText('MicroSaaS')

      expect(createApiCalls).toHaveLength(1)
      const getIdToken = createApiCalls[0]

      // Prove it is genuinely live: change what the auth module resolves and
      // confirm the function App wired up picks up the new value, rather than
      // freezing whatever was true at the moment `createApi` was called.
      getFreshIdToken.mockResolvedValueOnce('refreshed-token')
      await expect(getIdToken()).resolves.toBe('refreshed-token')
      expect(getFreshIdToken).toHaveBeenCalled()
    })
  })
})
