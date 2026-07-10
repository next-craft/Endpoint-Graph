import '@testing-library/jest-dom'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import RepoList from '@/components/RepoList'
import { triggerAnalysis, fetchUserRepos, deleteService } from '@/lib/api'

const mockPush = jest.fn()

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}))

jest.mock('@/lib/api', () => ({
  triggerAnalysis: jest.fn(),
  fetchUserRepos: jest.fn(),
  deleteService: jest.fn(),
}))

const untrackedRepo = {
  name: 'my-repo',
  full_name: 'owner/my-repo',
  private: false,
  updated_at: '2024-01-01T00:00:00Z',
  tracked: false,
  last_analyzed_at: null,
  service_id: null,
}

const trackedRepo = {
  name: 'my-repo',
  full_name: 'owner/my-repo',
  private: false,
  updated_at: '2024-01-01T00:00:00Z',
  tracked: true,
  last_analyzed_at: '2024-06-01T12:00:00Z',
  service_id: 42,
}

beforeEach(() => {
  jest.clearAllMocks()
})

// --- Rendering ---

test('renders repo.name in the DOM', () => {
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  expect(screen.getByText('my-repo')).toBeInTheDocument()
})

test('renders repo.full_name in smaller muted text', () => {
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  expect(screen.getByText('owner/my-repo')).toBeInTheDocument()
})

test('shows Private badge text for private repos', () => {
  const privateRepo = { ...untrackedRepo, private: true }
  render(<RepoList repos={[privateRepo]} onUpdate={jest.fn()} />)
  expect(screen.getByText('Private')).toBeInTheDocument()
})

test('shows Public badge text for public repos', () => {
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  expect(screen.getByText('Public')).toBeInTheDocument()
})

test('Private badge uses the orange accent token (v2-open-issues.md issue 7)', () => {
  const privateRepo = { ...untrackedRepo, private: true }
  render(<RepoList repos={[privateRepo]} onUpdate={jest.fn()} />)
  const badge = screen.getByText('Private')
  expect(badge.className).toContain('bg-orange-100')
  expect(badge.className).toContain('text-orange')
  expect(badge.className).toContain('font-mono')
})

test('Public badge uses the neutral prussian/alabaster tokens (v2-open-issues.md issue 7)', () => {
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  const badge = screen.getByText('Public')
  expect(badge.className).toContain('bg-prussian-400')
  expect(badge.className).toContain('text-alabaster-300')
  expect(badge.className).toContain('font-mono')
})

test('shows Never when last_analyzed_at is null', () => {
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  expect(screen.getByText(/Never/)).toBeInTheDocument()
})

test('shows formatted date when last_analyzed_at is an ISO string', () => {
  render(<RepoList repos={[trackedRepo]} onUpdate={jest.fn()} />)
  expect(screen.queryByText(/Never/)).not.toBeInTheDocument()
  const expected = new Date(trackedRepo.last_analyzed_at).toLocaleString()
  const escaped = expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  expect(screen.getByText(new RegExp(escaped))).toBeInTheDocument()
})

// --- Button visibility ---

test('shows Track button only when tracked=false', () => {
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  expect(screen.getByRole('button', { name: 'Track' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Re-analyze' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Untrack' })).not.toBeInTheDocument()
})

test('shows Re-analyze and Untrack buttons only when tracked=true', () => {
  render(<RepoList repos={[trackedRepo]} onUpdate={jest.fn()} />)
  expect(screen.getByRole('button', { name: 'Re-analyze' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Untrack' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Track' })).not.toBeInTheDocument()
})

// --- Empty state ---

test('shows "No repositories found." paragraph when repos array is empty', () => {
  render(<RepoList repos={[]} onUpdate={jest.fn()} />)
  expect(screen.getByText('No repositories found.')).toBeInTheDocument()
})

test('does not render a list element when repos is empty', () => {
  render(<RepoList repos={[]} onUpdate={jest.fn()} />)
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
})

// --- Track action ---

test('Track click calls triggerAnalysis with the full GitHub HTTPS URL', async () => {
  triggerAnalysis.mockResolvedValue({ status: 'ok' })
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Track' }))
  await waitFor(() => {
    expect(triggerAnalysis).toHaveBeenCalledWith('https://github.com/owner/my-repo')
  })
})

test('Track click navigates to graph page with repo full_name after analysis succeeds', async () => {
  triggerAnalysis.mockResolvedValue({ status: 'ok' })
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Track' }))
  await waitFor(() => {
    expect(mockPush).toHaveBeenCalledWith('/graph?repo=owner/my-repo')
  })
})

test('Track shows "Tracking…" label and disables button while loading', async () => {
  triggerAnalysis.mockReturnValue(new Promise(() => {}))
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Track' }))
  await waitFor(() => {
    expect(screen.getByRole('button', { name: 'Tracking…' })).toBeDisabled()
  })
})

test('Track error displays error message inside the row', async () => {
  triggerAnalysis.mockRejectedValue(new Error('clone failed'))
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Track' }))
  await waitFor(() => {
    expect(screen.getByText('clone failed')).toBeInTheDocument()
  })
})

test('Track error re-enables the Track button after failure', async () => {
  triggerAnalysis.mockRejectedValue(new Error('clone failed'))
  render(<RepoList repos={[untrackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Track' }))
  await waitFor(() => {
    expect(screen.getByRole('button', { name: 'Track' })).not.toBeDisabled()
  })
})

// --- Re-analyze action ---

test('Re-analyze click calls triggerAnalysis, then fetchUserRepos, then onUpdate with result', async () => {
  const updatedList = [{ ...trackedRepo, last_analyzed_at: '2024-07-01T00:00:00Z' }]
  triggerAnalysis.mockResolvedValue({ status: 'ok' })
  fetchUserRepos.mockResolvedValue(updatedList)
  const onUpdate = jest.fn()
  render(<RepoList repos={[trackedRepo]} onUpdate={onUpdate} />)
  fireEvent.click(screen.getByRole('button', { name: 'Re-analyze' }))
  await waitFor(() => {
    expect(triggerAnalysis).toHaveBeenCalledWith('https://github.com/owner/my-repo')
    expect(fetchUserRepos).toHaveBeenCalled()
    expect(onUpdate).toHaveBeenCalledWith(updatedList)
  })
})

test('Re-analyze shows "Analyzing…" label and disables both buttons while loading', async () => {
  triggerAnalysis.mockReturnValue(new Promise(() => {}))
  render(<RepoList repos={[trackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Re-analyze' }))
  await waitFor(() => {
    expect(screen.getByRole('button', { name: 'Analyzing…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Untrack' })).toBeDisabled()
  })
})

test('Re-analyze error displays error message inside the row', async () => {
  triggerAnalysis.mockRejectedValue(new Error('analysis failed'))
  render(<RepoList repos={[trackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Re-analyze' }))
  await waitFor(() => {
    expect(screen.getByText('analysis failed')).toBeInTheDocument()
  })
})

test('Re-analyze error clears loading state and re-enables both buttons', async () => {
  triggerAnalysis.mockRejectedValue(new Error('analysis failed'))
  render(<RepoList repos={[trackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Re-analyze' }))
  await waitFor(() => {
    expect(screen.getByRole('button', { name: 'Re-analyze' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: 'Untrack' })).not.toBeDisabled()
  })
})

// --- Untrack action ---

test('Untrack click calls deleteService with the repo service_id', async () => {
  deleteService.mockResolvedValue({ status: 'deleted' })
  render(<RepoList repos={[trackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Untrack' }))
  await waitFor(() => {
    expect(deleteService).toHaveBeenCalledWith(42)
  })
})

test('Untrack click calls fetchUserRepos, then onUpdate with the refreshed list', async () => {
  const refreshedList = [{ ...trackedRepo, tracked: false, service_id: null, last_analyzed_at: null }]
  deleteService.mockResolvedValue({ status: 'deleted' })
  fetchUserRepos.mockResolvedValue(refreshedList)
  const onUpdate = jest.fn()
  render(<RepoList repos={[trackedRepo]} onUpdate={onUpdate} />)
  fireEvent.click(screen.getByRole('button', { name: 'Untrack' }))
  await waitFor(() => {
    expect(fetchUserRepos).toHaveBeenCalled()
    expect(onUpdate).toHaveBeenCalledWith(refreshedList)
  })
})

test('Untrack switches the row to untracked state immediately after delete, without waiting on the refetch (v2-open-issues.md issue 5)', async () => {
  deleteService.mockResolvedValue({ status: 'deleted' })
  fetchUserRepos.mockReturnValue(new Promise(() => {})) // never resolves
  const onUpdate = jest.fn()
  render(<RepoList repos={[trackedRepo]} onUpdate={onUpdate} />)
  fireEvent.click(screen.getByRole('button', { name: 'Untrack' }))
  await waitFor(() => {
    expect(onUpdate).toHaveBeenCalledWith([
      { ...trackedRepo, tracked: false, service_id: null, last_analyzed_at: null },
    ])
  })
})

test('Untrack reflects untracked state even when the follow-up refetch fails, and does not show a row error', async () => {
  deleteService.mockResolvedValue({ status: 'deleted' })
  fetchUserRepos.mockRejectedValue(new Error('network error'))
  const onUpdate = jest.fn()
  render(<RepoList repos={[trackedRepo]} onUpdate={onUpdate} />)
  fireEvent.click(screen.getByRole('button', { name: 'Untrack' }))
  await waitFor(() => {
    expect(onUpdate).toHaveBeenCalledWith([
      { ...trackedRepo, tracked: false, service_id: null, last_analyzed_at: null },
    ])
  })
  expect(screen.queryByText('network error')).not.toBeInTheDocument()
})

test('Untrack shows "Untracking…" label and disables both row buttons while loading', async () => {
  deleteService.mockReturnValue(new Promise(() => {}))
  render(<RepoList repos={[trackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Untrack' }))
  await waitFor(() => {
    expect(screen.getByRole('button', { name: 'Untracking…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Re-analyze' })).toBeDisabled()
  })
})

test('Untrack error displays error message inside the row', async () => {
  deleteService.mockRejectedValue(new Error('delete failed'))
  render(<RepoList repos={[trackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Untrack' }))
  await waitFor(() => {
    expect(screen.getByText('delete failed')).toBeInTheDocument()
  })
})

test('Untrack error clears loading state and re-enables both buttons', async () => {
  deleteService.mockRejectedValue(new Error('delete failed'))
  render(<RepoList repos={[trackedRepo]} onUpdate={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Untrack' }))
  await waitFor(() => {
    expect(screen.getByRole('button', { name: 'Untrack' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: 'Re-analyze' })).not.toBeDisabled()
  })
})

// --- Multiple repos ---

test('renders two repos independently with correct action buttons per tracked state', () => {
  const anotherRepo = {
    name: 'other-repo',
    full_name: 'owner/other-repo',
    private: true,
    updated_at: '2024-02-01T00:00:00Z',
    tracked: true,
    last_analyzed_at: null,
    service_id: 99,
  }
  render(<RepoList repos={[untrackedRepo, anotherRepo]} onUpdate={jest.fn()} />)
  expect(screen.getByText('my-repo')).toBeInTheDocument()
  expect(screen.getByText('other-repo')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Track' })).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: 'Re-analyze' })).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: 'Untrack' })).toHaveLength(1)
})

test('Untrack targets only the clicked repo\'s service_id when multiple repos are rendered', async () => {
  const anotherRepo = {
    name: 'other-repo',
    full_name: 'owner/other-repo',
    private: false,
    updated_at: '2024-02-01T00:00:00Z',
    tracked: true,
    last_analyzed_at: null,
    service_id: 99,
  }
  const refreshedList = [
    { ...trackedRepo, tracked: false, service_id: null, last_analyzed_at: null },
    anotherRepo,
  ]
  deleteService.mockResolvedValue({ status: 'deleted' })
  fetchUserRepos.mockResolvedValue(refreshedList)
  const onUpdate = jest.fn()
  render(<RepoList repos={[trackedRepo, anotherRepo]} onUpdate={onUpdate} />)

  const untrackButtons = screen.getAllByRole('button', { name: 'Untrack' })
  fireEvent.click(untrackButtons[0])

  await waitFor(() => {
    expect(deleteService).toHaveBeenCalledWith(42)
    expect(onUpdate).toHaveBeenCalledWith(refreshedList)
  })
})
