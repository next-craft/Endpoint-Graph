/**
 * Independent tests for app/graph/GraphPageInner.jsx (spec v2-08-scoped-graph,
 * updated for spec v2-11's endpoint-level node model).
 *
 * Derived by reading the implemented component directly -- not from the
 * spec's own "Test cases" section and not from any other pre-existing test
 * file for this page. Covers the core v2-08 behavior: reading `repo` from
 * the URL, fetching on mount, re-fetching when the URL changes, and the
 * loading/empty/error states around that fetch -- plus v2-11's raw
 * GraphNode/GraphEdge shape and the ep:/caller: id scheme.
 *
 * DependencyGraph now does its own raw-node -> React Flow transformation
 * internally (using @dagrejs/dagre), so it's replaced here with a
 * lightweight stand-in that renders each raw node's label and forwards
 * clicks to onNodeClick with an RF-shaped { id, data } node, matching what
 * the real component passes through from ReactFlow.
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
  return function MockImpactPanel({ endpointId, method, path, functionName, onClose }) {
    return (
      <div data-testid="impact-panel">
        <span data-testid="impact-panel-id">{endpointId}</span>
        <span data-testid="impact-panel-method">{method}</span>
        <span data-testid="impact-panel-path">{path}</span>
        <span data-testid="impact-panel-function-name">{functionName}</span>
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
          <div
            key={n.id}
            data-testid={`node-${n.id}`}
            onClick={() => onNodeClick(null, { id: n.id, data: n })}
          >
            {n.label}
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

const CALLER_NODE = {
  id: 'caller:1:lib/api.js:fetchUser',
  node_type: 'caller',
  label: 'fetchUser',
  function_name: 'fetchUser',
  method: null,
  path: null,
  file_path: 'lib/api.js',
  service_name: 'order-service',
  service_id: 1,
}

const ENDPOINT_NODE = {
  id: 'ep:10',
  node_type: 'endpoint',
  label: 'get_user\nGET /users/{id}',
  function_name: 'get_user',
  method: 'GET',
  path: '/users/{id}',
  file_path: 'routers/users.py',
  service_name: 'user-service',
  service_id: 2,
}

const ONE_EDGE = {
  source: CALLER_NODE.id,
  target: ENDPOINT_NODE.id,
  call_count: 5,
  last_seen_at: '2024-01-01T00:00:00Z',
}

// ---------------------------------------------------------------------------
// Happy path
// ---------------------------------------------------------------------------

describe('GraphPageInner - happy path', () => {
  test('fetches the graph for the repo id in the URL and renders returned nodes and edges', async () => {
    mockSearchParamsGet.mockReturnValue('acme/sample-services')
    fetchGraph.mockResolvedValue({
      nodes: [CALLER_NODE, ENDPOINT_NODE],
      edges: [ONE_EDGE],
    })

    render(<GraphPageInner />)

    await waitFor(() => expect(fetchGraph).toHaveBeenCalledWith('acme/sample-services'))
    await screen.findByTestId('dependency-graph')

    expect(screen.getByTestId('node-count')).toHaveTextContent('2')
    expect(screen.getByTestId('edge-count')).toHaveTextContent('1')
    expect(screen.getByTestId(`node-${ENDPOINT_NODE.id}`)).toHaveTextContent('GET /users/{id}')
  })

  test('clicking an endpoint node opens the impact panel with the endpoint id, method, path, and function name', async () => {
    mockSearchParamsGet.mockReturnValue('acme/sample-services')
    fetchGraph.mockResolvedValue({
      nodes: [CALLER_NODE, ENDPOINT_NODE],
      edges: [],
    })

    render(<GraphPageInner />)
    await screen.findByTestId(`node-${ENDPOINT_NODE.id}`)

    fireEvent.click(screen.getByTestId(`node-${ENDPOINT_NODE.id}`))

    expect(screen.getByTestId('impact-panel')).toBeInTheDocument()
    expect(screen.getByTestId('impact-panel-id')).toHaveTextContent('10')
    expect(screen.getByTestId('impact-panel-method')).toHaveTextContent('GET')
    expect(screen.getByTestId('impact-panel-path')).toHaveTextContent('/users/{id}')
    expect(screen.getByTestId('impact-panel-function-name')).toHaveTextContent('get_user')
  })

  test('clicking a caller node does not open the impact panel', async () => {
    mockSearchParamsGet.mockReturnValue('acme/sample-services')
    fetchGraph.mockResolvedValue({
      nodes: [CALLER_NODE],
      edges: [],
    })

    render(<GraphPageInner />)
    await screen.findByTestId(`node-${CALLER_NODE.id}`)

    fireEvent.click(screen.getByTestId(`node-${CALLER_NODE.id}`))

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
      nodes: [{ ...CALLER_NODE, id: 'caller:1:lib/a.js:fnA', label: 'fnA', service_name: 'repo-a-service' }],
      edges: [],
    })

    const { rerender } = render(<GraphPageInner />)

    await waitFor(() =>
      expect(screen.getByTestId('node-caller:1:lib/a.js:fnA')).toHaveTextContent('fnA')
    )

    mockSearchParamsGet.mockReturnValue('acme/repo-b')
    fetchGraph.mockResolvedValueOnce({
      nodes: [{ ...CALLER_NODE, id: 'caller:2:lib/b.js:fnB', label: 'fnB', service_name: 'repo-b-service' }],
      edges: [],
    })

    rerender(<GraphPageInner />)

    await waitFor(() => {
      expect(fetchGraph).toHaveBeenCalledTimes(2)
      expect(fetchGraph).toHaveBeenNthCalledWith(2, 'acme/repo-b')
    })

    await waitFor(() => {
      expect(screen.queryByTestId('node-caller:1:lib/a.js:fnA')).not.toBeInTheDocument()
      expect(screen.getByTestId('node-caller:2:lib/b.js:fnB')).toHaveTextContent('fnB')
    })
  })
})
