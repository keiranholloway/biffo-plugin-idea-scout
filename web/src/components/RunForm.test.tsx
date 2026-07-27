import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { RunForm } from './RunForm'

const BUILD_TYPES = [
  { key: 'micro-saas', label: 'MicroSaaS', description: 'One narrow job.' },
  { key: 'mobile-app', label: 'Mobile Application', description: null },
]
const LEVELS = [
  { value: 1, label: 'very small and niche' },
  { value: 3, label: 'moderate' },
  { value: 5, label: 'high-complexity' },
]

describe('RunForm', () => {
  it('cannot be submitted until a build type is chosen', () => {
    render(
      <RunForm buildTypes={BUILD_TYPES} complexityLevels={LEVELS} busy={false} onStart={vi.fn()} />,
    )

    expect(screen.getByRole('button', { name: 'Run now' })).toBeDisabled()
  })

  it('starts a run with the chosen type and complexity', async () => {
    const onStart = vi.fn()
    render(
      <RunForm buildTypes={BUILD_TYPES} complexityLevels={LEVELS} busy={false} onStart={onStart} />,
    )

    await userEvent.selectOptions(screen.getByRole('combobox'), 'mobile-app')
    await userEvent.click(screen.getByRole('button', { name: 'Run now' }))

    expect(onStart).toHaveBeenCalledWith('mobile-app', 3)
  })

  it('shows the chosen type’s description, because it feeds the research brief', async () => {
    render(
      <RunForm buildTypes={BUILD_TYPES} complexityLevels={LEVELS} busy={false} onStart={vi.fn()} />,
    )

    await userEvent.selectOptions(screen.getByRole('combobox'), 'micro-saas')

    expect(screen.getByText('One narrow job.')).toBeInTheDocument()
  })

  it('renders the complexity wording served by the API, not its own', () => {
    // The words the founder reads must be the words the agents are briefed
    // with; a second copy here would drift.
    render(
      <RunForm buildTypes={BUILD_TYPES} complexityLevels={LEVELS} busy={false} onStart={vi.fn()} />,
    )

    expect(screen.getByText('moderate')).toBeInTheDocument()
  })

  it('says a scout cannot be started when no categories are configured', () => {
    // An empty list is an admin problem the founder cannot fix — better than an
    // empty picker that silently rejects every submission.
    render(<RunForm buildTypes={[]} complexityLevels={LEVELS} busy={false} onStart={vi.fn()} />)

    expect(screen.getByText(/No build types are configured/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument()
  })

  it('tells the founder they can leave', () => {
    // The whole point of the fan-in work. If the UI does not say it, nobody
    // discovers it.
    render(
      <RunForm buildTypes={BUILD_TYPES} complexityLevels={LEVELS} busy={false} onStart={vi.fn()} />,
    )

    expect(screen.getByText(/close this tab/i)).toBeInTheDocument()
  })

  it('disables itself while a run is being started', () => {
    render(
      <RunForm buildTypes={BUILD_TYPES} complexityLevels={LEVELS} busy onStart={vi.fn()} />,
    )

    expect(screen.getByRole('button', { name: 'Starting…' })).toBeDisabled()
  })
})
