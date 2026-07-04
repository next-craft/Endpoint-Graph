/**
 * Independent tests for app/graph/GraphPageInner.jsx (spec v2-08-scoped-graph).
 *
 * Derived by reading the implemented component directly -- not from the
 * spec's own "Test cases" section and not from any other pre-existing test
 * file for this page. Covers the core v2-08 behavior: reading `repo` from
 * the URL, fetching on mount, re-fetching when the URL changes, and the
 * loading/empty/error states around that fetch.
 *
 * React Flow cannot run in Jest, so @/components/DependencyGraph is
 * replaced with a lightweight stand-in that exposes node/edge counts and
 * forwards clicks to onNodeClick -- the same shape recommended for mocking
 * @xyflow/react directly.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import GraphPageInner from '@/app/graph/GraphPageInner'
import { fetchGraph } from '@/lib/api'
import { supabase } from '@/lib/supabase'

const mockSearchParamsGet = jest.fn()

jest.mock('next/navigation', () => ({
  useSearchParams: () => ({ get: mockSearchParamsGet }),
}))

jest.mock('@/lib/api', () => ({
  fetchGraph: jest.fn(),
}))

jest.mock('@/lib/supabase', () => ({
  supabase: { auth: { signOut: jest.fn().mockResolvedValue(undefined) } },
}))

// AuthGuard concerns session/login redirect, not graph scoping -- bypass it.
jest.mock('@/components/AuthGuard', () => {
  return function MockAuthGuard({ children }) {
    return <>{children}</>
  }
})

jest.mock('@/components/ImpactPanel', () => {
  return function MockImpactPanel({ endpointId, endpointLabel, onClose }) {
    return (
      <div data-testid="impact-panel">
        <span data-testid="impact-panel-id">{endpointId}</span>
        <span data-testid="impact-panel-label">{endpointLabel}</span>
        <button onClick={onClose}>close-panel</button>
      </div>
    )
  }
})

jest.mock('@/components/DependencyGraph', () => {
  return function MockDependencyGraph({ nodes, edges, onNodeClick }) {
    return (
      <div data-testid="dependency-graph">
        <div data-testid="node-count">{nodes.length}</div>
        <div data-testid="edge-count">{edges.length}</div>
        {nodes.map((n) => (
          <div key={n.id} data-testid={`node-${n.id}`} onClick={() => onNodeClick(null, n)}>
            {n.data.label}
          </div>
        ))}
      </div>
    )
  }
})

// dynamic() is called with a loader that would `import()` the real
// DependencyGraph -- ignore the loader and hand back the mocked module
// directly so the component renders synchronously in tests.
jest.mock('next/dynamic', () => () => require('@/components/DependencyGraph'))

beforeEach(() => {
  jest.clearAllMocks()
  supabase.auth.signOut.mockResolvedValue(undefined)
})

// ---------------------------------------------------------------------------
// Happy path
// ---------------------------------------------------------------------------

describe('GraphPageInner - happy path', () => {
  test('fetches the graph for the repo id in the URL and renders returned nodes and edges', async () => {
    mockSearchParamsGet.mockReturnValue('acme/sample-services')
    fetchGraph.mockResolvedValue({
      nodes: [
        { id: '1', name: 'order-service' },
        { id: 'endpoint-10', name: 'GET /users/{id}' },
      ],
      edges: [
        {
          source: '1',
          target: 'endpoint-10',
          endpoint_method: 'GET',
          endpoint_path: '/users/{id}',
          call_count: 5,
          last_seen_at: '2024-01-01T00:00:00Z',
        },
      ],
    })

    render(<GraphPageInner />)

    await waitFor(() => expect(fetchGraph).toHaveBeenCalledWith('acme/sample-services'))
    await screen.findByTestId('dependency-graph')

    expect(screen.getByTestId('node-count')).toHaveTextContent('2')
    expect(screen.getByTestId('edge-count')).toHaveTextContent('1')
    expect(screen.getByTestId('node-endpoint-10')).toHaveTextContent('GET /users/{id}')
  })

  test('clicking an endpoint node opens the impact panel with the parsed endpoint id and label', async () => {
    mockSearchParamsGet.mockReturnValue('acme/sample-services')
    fetchGraph.mockResolvedValue({
      nodes: [
        { id: '1', name: 'order-service' },
        { id: 'endpoint-10', name: 'GET /users/{id}' },
      ],
      edges: [],
    })

    render(<GraphPageInner />)
    await screen.findByTestId('node-endpoint-10')

    fireEvent.click(screen.getByTestId('node-endpoint-10'))

    expect(screen.getByTestId('impact-panel')).toBeInTheDocument()
    expect(screen.getByTestId('impact-panel-id')).toHaveTextContent('10')
    expect(screen.getByTestId('impact-panel-label')).toHaveTextContent('GET /users/{id}')
  })

  test('clicking a service node does not open the impact panel', async () => {
    mockSearchParamsGet.mockReturnValue('acme/sample-services')
    fetchGraph.mockResolvedValue({
      nodes: [{ id: '1', name: 'order-service' }],
      edges: [],
    })

    render(<GraphPageInner />)
    await screen.findByTestId('node-1')

    fireEvent.click(screen.getByTestId('node-1'))

    expect(screen.queryByTestId('impact-panel')).not.toBeInTheDocument()
  })

  test('logout button signs out of supabase and redirects to /login', async () => {
    mockSearchParamsGet.mockReturnValue(null)
    const originalLocation = window.location
    delete window.location
    window.location = { href: '' }

    render(<GraphPageInner />)

    fireEvent.click(screen.getByText('logout'))

    await waitFor(() => expect(supabase.auth.signOut).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(window.location.href).toBe('/login'))

    window.location = originalLocation
  })
})

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

describe('GraphPageInner - edge cases', () => {
  test('shows the no-repo empty state and never calls fetchGraph when the URL has no repo param', async () => {
    mockSearchParamsGet.mockReturnValue(null)

    render(<GraphPageInner />)

    expect(await screen.findByText(/No repo selected/i)).toBeInTheDocument()
    expect(fetchGraph).not.toHaveBeenCalled()
  })

  test('shows the repo-specific empty state when the repo has no tracked data', async () => {
    mockSearchParamsGet.mockReturnValue('acme/empty-repo')
    fetchGraph.mockResolvedValue({ nodes: [], edges: [] })

    render(<GraphPageInner />)

    expect(await screen.findByText(/This repo has no tracked services yet\./i)).toBeInTheDocument()
    expect(screen.queryByTestId('dependency-graph')).not.toBeInTheDocument()
  })

  test('shows a loading indicator while the graph request is in flight, then hides it', async () => {
    mockSearchParamsGet.mockReturnValue('acme/sample-services')
    let resolveFetch
    fetchGraph.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve
      })
    )

    render(<GraphPageInner />)

    expect(screen.getByText('Loading graph…')).toBeInTheDocument()

    resolveFetch({ nodes: [], edges: [] })

    await waitFor(() => expect(screen.queryByText('Loading graph…')).not.toBeInTheDocument())
  })
})

// ---------------------------------------------------------------------------
// Error cases
// ---------------------------------------------------------------------------

describe('GraphPageInner - error cases', () => {
  test('shows the thrown error message when fetchGraph rejects', async () => {
    mockSearchParamsGet.mockReturnValue('acme/sample-services')
    fetchGraph.mockRejectedValue(new Error('Session expired — please log in again'))

    render(<GraphPageInner />)

    expect(await screen.findByText('Session expired — please log in again')).toBeInTheDocument()
    expect(screen.queryByTestId('dependency-graph')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Integration (URL persistence / repo isolation)
// ---------------------------------------------------------------------------

describe('GraphPageInner - repo isolation across URL changes', () => {
  test('refetches and fully replaces the graph when the repo id in the URL changes', async () => {
    mockSearchParamsGet.mockReturnValue('acme/repo-a')
    fetchGraph.mockResolvedValueOnce({
      nodes: [{ id: '1', name: 'repo-a-service' }],
      edges: [],
    })

    const { rerender } = render(<GraphPageInner />)

    await waitFor(() => expect(screen.getByTestId('node-1')).toHaveTextContent('repo-a-service'))

    mockSearchParamsGet.mockReturnValue('acme/repo-b')
    fetchGraph.mockResolvedValueOnce({
      nodes: [{ id: '2', name: 'repo-b-service' }],
      edges: [],
    })

    rerender(<GraphPageInner />)

    await waitFor(() => {
      expect(fetchGraph).toHaveBeenCalledTimes(2)
      expect(fetchGraph).toHaveBeenNthCalledWith(2, 'acme/repo-b')
    })

    await waitFor(() => {
      expect(screen.queryByTestId('node-1')).not.toBeInTheDocument()
      expect(screen.getByTestId('node-2')).toHaveTextContent('repo-b-service')
    })
  })
})
