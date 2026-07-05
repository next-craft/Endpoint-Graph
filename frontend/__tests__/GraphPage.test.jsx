import '@testing-library/jest-dom'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import GraphPage from '@/app/graph/GraphPageInner'

jest.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: jest.fn().mockResolvedValue({ data: { session: null } }),
    },
  },
}))

jest.mock('@/components/AuthGuard', () => ({
  __esModule: true,
  default: function MockAuthGuard({ children }) {
    return children
  },
}))

jest.mock('@/components/DependencyGraph', () => ({
  __esModule: true,
  default: function MockDependencyGraph({ nodes, edges, onNodeClick }) {
    return (
      <div data-testid="dependency-graph">
        {nodes.map((n) => (
          <div
            key={n.id}
            data-testid={`node-${n.id}`}
            data-node-id={n.id}
            data-label={n.label}
            onClick={(e) => onNodeClick && onNodeClick(e, { id: n.id, data: n })}
          >
            {n.label}
          </div>
        ))}
        {edges.map((e) => (
          <div key={`${e.source}-${e.target}`} data-testid="graph-edge" data-edge-source={e.source} data-edge-target={e.target} />
        ))}
      </div>
    )
  },
}))

jest.mock('@/components/ImpactPanel', () => ({
  __esModule: true,
  default: function MockImpactPanel({ endpointId, method, path, functionName, onClose }) {
    return (
      <div
        data-testid="impact-panel"
        data-endpoint-id={String(endpointId)}
        data-method={method}
        data-path={path}
        data-function-name={functionName}
      >
        <button onClick={onClose}>Close</button>
      </div>
    )
  },
}))

jest.mock('next/dynamic', () => (_fn) => {
  return require('@/components/DependencyGraph').default
})

const mockUseSearchParams = jest.fn(() => new URLSearchParams('repo=iamaryan07/sample-services'))
jest.mock('next/navigation', () => ({
  useSearchParams: () => mockUseSearchParams(),
}))

jest.mock('@/lib/api', () => ({
  fetchGraph: jest.fn(),
}))

const { fetchGraph } = require('@/lib/api')

beforeEach(() => {
  jest.clearAllMocks()
  mockUseSearchParams.mockReturnValue(new URLSearchParams('repo=iamaryan07/sample-services'))
})

test('test_graph_page_transforms_fetchGraph_response', async () => {
  fetchGraph.mockResolvedValue({
    nodes: [
      {
        id: 'caller:1:lib/api.js:fetchUser', node_type: 'caller', label: 'fetchUser',
        function_name: 'fetchUser', method: null, path: null,
        file_path: 'lib/api.js', service_name: 'order-service', service_id: 1,
      },
      {
        id: 'ep:5', node_type: 'endpoint', label: 'get_user\nGET /users/{id}',
        function_name: 'get_user', method: 'GET', path: '/users/{id}',
        file_path: 'routers/users.py', service_name: 'user-service', service_id: 2,
      },
    ],
    edges: [
      {
        source: 'caller:1:lib/api.js:fetchUser',
        target: 'ep:5',
        call_count: 5,
        last_seen_at: '2024-01-01T00:00:00',
      },
    ],
  })

  render(<GraphPage />)

  await waitFor(() => {
    expect(screen.getByText('fetchUser')).toBeInTheDocument()
  })

  expect(fetchGraph).toHaveBeenCalledWith('iamaryan07/sample-services')

  const edge = screen.getByTestId('graph-edge')
  expect(edge).toHaveAttribute('data-edge-source', 'caller:1:lib/api.js:fetchUser')
  expect(edge).toHaveAttribute('data-edge-target', 'ep:5')
})

test('test_graph_page_shows_error_when_fetchGraph_fails', async () => {
  fetchGraph.mockRejectedValue(new Error('graph fetch failed'))

  render(<GraphPage />)

  await waitFor(() => {
    expect(screen.getByText('graph fetch failed')).toBeInTheDocument()
  })

  expect(screen.queryByText('Loading graph…')).not.toBeInTheDocument()
  expect(screen.queryByTestId('dependency-graph')).not.toBeInTheDocument()
})

test('test_handleNodeClick_ignores_caller_nodes', async () => {
  fetchGraph.mockResolvedValue({
    nodes: [{
      id: 'caller:1:lib/api.js:fetchUser', node_type: 'caller', label: 'fetchUser',
      function_name: 'fetchUser', method: null, path: null,
      file_path: 'lib/api.js', service_name: 'order-service', service_id: 1,
    }],
    edges: [],
  })

  render(<GraphPage />)

  await waitFor(() => {
    expect(screen.getByText('fetchUser')).toBeInTheDocument()
  })

  fireEvent.click(screen.getByText('fetchUser'))

  expect(screen.queryByTestId('impact-panel')).not.toBeInTheDocument()
})

test('test_handleNodeClick_sets_state_for_endpoint_nodes', async () => {
  fetchGraph.mockResolvedValue({
    nodes: [
      {
        id: 'caller:1:lib/api.js:fetchUser', node_type: 'caller', label: 'fetchUser',
        function_name: 'fetchUser', method: null, path: null,
        file_path: 'lib/api.js', service_name: 'order-service', service_id: 1,
      },
      {
        id: 'ep:5', node_type: 'endpoint', label: 'get_user\nGET /users/{id}',
        function_name: 'get_user', method: 'GET', path: '/users/{id}',
        file_path: 'routers/users.py', service_name: 'user-service', service_id: 2,
      },
    ],
    edges: [],
  })

  render(<GraphPage />)

  await waitFor(() => {
    expect(screen.getByTestId('node-ep:5')).toBeInTheDocument()
  })

  fireEvent.click(screen.getByTestId('node-ep:5'))

  await waitFor(() => {
    expect(screen.getByTestId('impact-panel')).toBeInTheDocument()
  })

  expect(screen.getByTestId('impact-panel')).toHaveAttribute('data-endpoint-id', '5')
  expect(screen.getByTestId('impact-panel')).toHaveAttribute('data-method', 'GET')
  expect(screen.getByTestId('impact-panel')).toHaveAttribute('data-path', '/users/{id}')
  expect(screen.getByTestId('impact-panel')).toHaveAttribute('data-function-name', 'get_user')
})

test('test_graph_page_shows_empty_state_when_no_repo_param', async () => {
  mockUseSearchParams.mockReturnValue(new URLSearchParams())

  render(<GraphPage />)

  await waitFor(() => {
    expect(screen.getByText('No repo selected — go to /repos and track one.')).toBeInTheDocument()
  })

  expect(fetchGraph).not.toHaveBeenCalled()
})
