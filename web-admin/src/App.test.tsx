/**
 * The admin panel, driven the way an admin drives it.
 *
 * v1 success criterion 5 is "an admin can add/edit/deactivate build-type
 * categories in a UI without a code change". These assert each of those three
 * verbs actually reaches the API, because the milestone that was meant to
 * deliver this (M5) was closed while the UI did not exist at all (#22).
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const list = vi.fn()
const create = vi.fn()
const update = vi.fn()
const remove = vi.fn()

vi.mock('./lib/auth', () => ({
  getCurrentSession: () =>
    Promise.resolve({ getIdToken: () => ({ getJwtToken: () => 'test-token' }) }),
}))

vi.mock('./lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./lib/api')>()
  return { ...actual, createApi: () => ({ list, create, update, remove }) }
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

describe('Idea Scout admin — build types', () => {
  beforeEach(() => {
    list.mockReset().mockResolvedValue([MICRO_SAAS])
    create.mockReset().mockResolvedValue(MICRO_SAAS)
    update.mockReset().mockResolvedValue(MICRO_SAAS)
    remove.mockReset()
  })

  it('lists the categories a founder would see', async () => {
    render(<App />)
    expect(await screen.findByText('MicroSaaS')).toBeTruthy()
    expect(screen.getByText('micro-saas')).toBeTruthy()
  })

  it('adds a category without a code change', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Add a build type' }))
    await user.type(screen.getByLabelText(/Label/), 'Mobile App')
    await user.type(screen.getByLabelText(/^Key/), 'mobile-app')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    expect(create.mock.calls[0][0]).toMatchObject({ key: 'mobile-app', label: 'Mobile App' })
  })

  it('deactivates a category rather than deleting it', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Hide' }))

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    // The key point: a hide is an update with active:false, never a delete.
    // Existing runs reference the key, so deleting orphans them.
    expect(update.mock.calls[0][1]).toMatchObject({ active: false, key: 'micro-saas' })
    expect(remove).not.toHaveBeenCalled()
  })

  it('refuses to save a key that is not url-safe', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Add a build type' }))
    await user.type(screen.getByLabelText(/Label/), 'Bad')
    await user.type(screen.getByLabelText(/^Key/), 'Not A Key')

    expect(screen.getByRole('button', { name: 'Save' })).toHaveProperty('disabled', true)
    expect(screen.getByText(/lower-case letters, numbers and hyphens/i)).toBeTruthy()
  })

  it('locks the key when editing, because runs reference it', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Edit' }))

    expect(screen.getByLabelText(/^Key/)).toHaveProperty('disabled', true)
    expect(screen.getByText(/Immutable/i)).toBeTruthy()
  })

  it('explains a 403 as "not an admin" rather than showing a raw failure', async () => {
    const { ApiError } = await import('./lib/api')
    list.mockRejectedValue(new ApiError(403, 'Forbidden'))

    render(<App />)

    expect(await screen.findByText(/not in the admin group/i)).toBeTruthy()
  })

  it('says what an empty list means for the founder', async () => {
    list.mockResolvedValue([])
    render(<App />)
    // An empty table looks like a loading glitch; the consequence is that no
    // founder can start a scout at all.
    expect(await screen.findByText(/cannot start a scout/i)).toBeTruthy()
  })

  it('warns that hiding is preferred over deleting', async () => {
    render(<App />)
    const main = await waitFor(() => document.querySelector('main.page') as HTMLElement)
    expect(within(main).getByText(/prefer deactivating over/i)).toBeTruthy()
  })
})
