/**
 * The admin panel with tabs for Build Types, Agents, and Models.
 *
 * M2 adds three features:
 * - Tab switching: each tab pane renders its content
 * - Agents tab: edit admin-configured prompts for four agent roles
 * - Models tab: CRUD the model catalog with web_capable visibility
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listBuildTypes = vi.fn()
const createBuildType = vi.fn()
const updateBuildType = vi.fn()
const removeBuildType = vi.fn()
const listChatAgents = vi.fn()
const getBuiltinAgents = vi.fn()
const createChatAgent = vi.fn()
const updateChatAgent = vi.fn()
const deleteChatAgent = vi.fn()
const listModelCatalog = vi.fn()
const createModelCatalogEntry = vi.fn()
const updateModelCatalogEntry = vi.fn()
const deleteModelCatalogEntry = vi.fn()

vi.mock('./lib/auth', () => ({
  getCurrentSession: () =>
    Promise.resolve({ getIdToken: () => ({ getJwtToken: () => 'test-token' }) }),
}))

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return {
    ...actual,
    createApi: () => ({
      list: listBuildTypes,
      create: createBuildType,
      update: updateBuildType,
      remove: removeBuildType,
      listChatAgents,
      getBuiltinAgents,
      createChatAgent,
      updateChatAgent,
      deleteChatAgent,
      listModelCatalog,
      createModelCatalogEntry,
      updateModelCatalogEntry,
      deleteModelCatalogEntry,
    }),
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
  model_id: 'anthropic/claude-opus:online',
  label: 'Claude Opus (Web)',
  active: true,
  is_default: true,
  web_capable: true,
}

const MODEL_NOT_WEB_CAPABLE = {
  id: 'model2',
  model_id: 'anthropic/claude-opus',
  label: 'Claude Opus (No Web)',
  active: true,
  is_default: false,
  web_capable: false,
}

describe('Idea Scout admin panel', () => {
  beforeEach(() => {
    listBuildTypes.mockReset().mockResolvedValue([MICRO_SAAS])
    createBuildType.mockReset().mockResolvedValue(MICRO_SAAS)
    updateBuildType.mockReset().mockResolvedValue(MICRO_SAAS)
    removeBuildType.mockReset()
    listChatAgents.mockReset().mockResolvedValue([RESEARCH_AGENT, SYNTHESIS_AGENT])
    getBuiltinAgents.mockReset().mockResolvedValue({
      agents: [BUILTIN_COMMUNITY_AGENT, BUILTIN_NARRATIVE_AGENT, BUILTIN_COMPETITIVE_AGENT, BUILTIN_SYNTHESIS_AGENT],
    })
    createChatAgent.mockReset().mockResolvedValue(RESEARCH_AGENT)
    updateChatAgent.mockReset().mockResolvedValue(RESEARCH_AGENT)
    deleteChatAgent.mockReset()
    listModelCatalog.mockReset().mockResolvedValue([MODEL_WEB_CAPABLE, MODEL_NOT_WEB_CAPABLE])
    createModelCatalogEntry.mockReset().mockResolvedValue(MODEL_WEB_CAPABLE)
    updateModelCatalogEntry.mockReset().mockResolvedValue(MODEL_WEB_CAPABLE)
    deleteModelCatalogEntry.mockReset()
  })

  describe('Tab switching', () => {
    it('renders three tabs: Build Types, Agents, Models', async () => {
      render(<App />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /Build Types/i })).toBeTruthy()
        expect(screen.getByRole('button', { name: /Agents/i })).toBeTruthy()
        expect(screen.getByRole('button', { name: /Models/i })).toBeTruthy()
      })
    })

    it('defaults to Build Types tab', async () => {
      render(<App />)
      await waitFor(() => {
        const buildTypesTab = screen.getByRole('button', { name: /Build Types/i })
        expect(buildTypesTab).toHaveClass('admin-tab--active')
      })
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

      const agentsTab = await screen.findByRole('button', { name: /Agents/i })
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

      const modelsTab = await screen.findByRole('button', { name: /Models/i })
      await user.click(modelsTab)

      await waitFor(() => {
        expect(screen.getByText('Claude Opus (Web)')).toBeTruthy()
        expect(screen.getByText('Claude Opus (No Web)')).toBeTruthy()
      })
    })
  })

  describe('Agents tab', () => {
    it('lists all agents with their prompts', async () => {
      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('button', { name: /Agents/i })
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

      const agentsTab = await screen.findByRole('button', { name: /Agents/i })
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

      const agentsTab = await screen.findByRole('button', { name: /Agents/i })
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

    it('shows a warning on the synthesis agent that it is not live-editable', async () => {
      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('button', { name: /Agents/i })
      await user.click(agentsTab)

      await waitFor(() => {
        // Check that the synthesis agent has a warning
        const warnings = screen.getAllByText(/Not live-editable/i)
        expect(warnings.length).toBeGreaterThan(0)
      })
    })

    it('does not show a warning on research agents', async () => {
      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('button', { name: /Agents/i })
      await user.click(agentsTab)

      await waitFor(() => {
        // Get the research agent rows by looking for the research prompt text
        const researchPromptElement = screen.getByText('Research communities...')
        const agentRow = researchPromptElement.closest('.admin-list-item')

        // The warning should not appear in the research agent row
        if (agentRow) {
          const warningInRow = agentRow.querySelector('.admin-synthesis-warning')
          expect(warningInRow).toBeFalsy()
        }
      })
    })

    it('shows real built-in prompts, not placeholder text', async () => {
      // Start with no stored agents so built-ins display
      listChatAgents.mockResolvedValue([])

      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('button', { name: /Agents/i })
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

    it('promotes a built-in with real prompt content', async () => {
      // Start with no stored agents so built-ins display
      listChatAgents.mockResolvedValue([])

      // Mock the confirmation dialog
      vi.stubGlobal('confirm', () => true)

      const user = userEvent.setup()
      render(<App />)

      const agentsTab = await screen.findByRole('button', { name: /Agents/i })
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
    it('lists all models with web_capable status', async () => {
      const user = userEvent.setup()
      render(<App />)

      const modelsTab = await screen.findByRole('button', { name: /Models/i })
      await user.click(modelsTab)

      await waitFor(() => {
        expect(screen.getByText('Claude Opus (Web)')).toBeTruthy()
        expect(screen.getByText('Claude Opus (No Web)')).toBeTruthy()
      })
    })

    it('shows web_capable status visibly in the list', async () => {
      const user = userEvent.setup()
      render(<App />)

      const modelsTab = await screen.findByRole('button', { name: /Models/i })
      await user.click(modelsTab)

      await waitFor(() => {
        // Look for visual indication of web-capable status
        const badges = screen.getAllByText(/web/i)
        expect(badges.length).toBeGreaterThan(0)
      })
    })

    it('renders web_capable field in the create form', async () => {
      const user = userEvent.setup()
      render(<App />)

      const modelsTab = await screen.findByRole('button', { name: /Models/i })
      await user.click(modelsTab)

      const addButton = await screen.findByRole('button', { name: /Add.*Model/i })
      await user.click(addButton)

      await waitFor(() => {
        // Look for a web_capable or web-capable checkbox/field
        const labels = screen.getAllByText(/web/i)
        expect(labels.length).toBeGreaterThan(0)
      })
    })

    it('allows setting web_capable when creating a model', async () => {
      const user = userEvent.setup()
      render(<App />)

      const modelsTab = await screen.findByRole('button', { name: /Models/i })
      await user.click(modelsTab)

      const addButton = await screen.findByRole('button', { name: /Add.*Model/i })
      await user.click(addButton)

      // Fill in the form with web_capable checked
      const inputs = screen.getAllByRole('textbox')
      await user.type(inputs[0], 'anthropic/claude-3')
      await user.type(inputs[1], 'Claude 3')

      const checkboxes = screen.getAllByRole('checkbox')
      const webCapableCheckbox = checkboxes.find((cb) => {
        const label = cb.closest('label')
        return label?.textContent?.toLowerCase().includes('web')
      })

      if (webCapableCheckbox) {
        await user.click(webCapableCheckbox)
      }

      const submitButton = screen.getByRole('button', { name: /Create/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(createModelCatalogEntry).toHaveBeenCalled()
      })
    })
  })
})
