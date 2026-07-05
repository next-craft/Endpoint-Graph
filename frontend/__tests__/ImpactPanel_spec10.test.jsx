/**
 * Spec-10 tests for ImpactPanel, GraphPage node-click wiring, and
 * fetchImpactAnalysis error propagation in api.js.
 * Updated for spec v2-11: ImpactPanel takes method/path/functionName props
 * (not endpointLabel), consumer rows render caller function/file context,
 * and graph node ids follow the ep:/caller: scheme.
 *
 * ImpactPanel is intentionally NOT mocked here so that
 * - direct ImpactPanel tests render the real component, and
 * - GraphPage integration tests verify the actual panel appears/disappears.
 */

import '@testing-library/jest-dom'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ImpactPanel from '@/components/ImpactPanel'
import GraphPage from '@/app/graph/GraphPageInner'

// ─── Module mocks (hoisted by Jest) ──────────────────────────────────────────

jest.mock('@/lib/api', () => ({
  fetchImpactAnalysis: jest.fn(),
  fetchGraph: jest.fn(),
  triggerAnalysis: jest.fn(),
}))

const mockUseSearchParams = jest.fn(() => new URLSearchParams('repo=iamaryan07/sample-services'))
jest.mock('next/navigation', () => ({
  useSearchParams: () => mockUseSearchParams(),
}))

jest.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: jest.fn().mockResolvedValue({
        data: { session: { provider_token: 'test-token', access_token: 'test-jwt' } },
      }),
    },
  },
}))

jest.mock('@/components/AuthGuard', () => ({
  __esModule: true,
  default: function MockAuthGuard({ children }) {
    return children
  },
}))

/**
 * MockDependencyGraph renders each raw node's label as a clickable div and
 * fires onNodeClick with an RF-shaped { id, data } node — the same shape
 * the real DependencyGraph passes through from ReactFlow's onNodeClick.
 */
jest.mock('@/components/DependencyGraph', () => ({
  __esModule: true,
  default: function MockDependencyGraph({ nodes, onNodeClick }) {
    return (
      <div data-testid="dependency-graph">
        {nodes.map((n) => (
          <div
            key={n.id}
            data-testid={`node-${n.id}`}
            onClick={(e) => onNodeClick && onNodeClick(e, { id: n.id, data: n })}
          >
            {n.label}
          </div>
        ))}
      </div>
    )
  },
}))

/** Replace next/dynamic with a synchronous pass-through. */
jest.mock('next/dynamic', () => (_fn) => {
  return require('@/components/DependencyGraph').default
})

const { fetchImpactAnalysis, fetchGraph, triggerAnalysis } = require('@/lib/api')

beforeEach(() => {
  jest.clearAllMocks()
  process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8000'
  mockUseSearchParams.mockReturnValue(new URLSearchParams('repo=iamaryan07/sample-services'))
  // Default: analysis succeeds so GraphPage integration tests can load the graph
  triggerAnalysis.mockResolvedValue({ status: 'ok' })
})

// ─── ImpactPanel direct tests ─────────────────────────────────────────────────

const baseProps = {
  endpointId: 1,
  method: 'GET',
  path: '/users/{id}',
  functionName: 'get_user',
  onClose: jest.fn(),
}

/**
 * The path prop is rendered in the panel header.
 */
test('impact_panel_renders_path_in_header', async () => {
  fetchImpactAnalysis.mockResolvedValue([])
  render(<ImpactPanel {...baseProps} path="/orders/create" method="POST" />)
  expect(screen.getByText('/orders/create')).toBeInTheDocument()
  expect(screen.getByText('POST')).toBeInTheDocument()
})

/**
 * The section label "Impact Analysis" is always visible in the panel header,
 * not conditional on loading or error state.
 */
test('impact_panel_shows_impact_analysis_section_label', () => {
  fetchImpactAnalysis.mockReturnValue(new Promise(() => {})) // never resolves
  render(<ImpactPanel {...baseProps} />)
  expect(screen.getByText('Impact Analysis')).toBeInTheDocument()
})

/**
 * call_count is shown via .toLocaleString() — the formatted number appears
 * next to the "calls" text.
 */
test('impact_panel_displays_call_count_in_consumer_row', async () => {
  fetchImpactAnalysis.mockResolvedValue([
    {
      service_name: 'billing-service',
      caller_function_name: 'chargeCard',
      caller_file_path: 'lib/billing.js',
      call_count: 999,
      last_seen_at: new Date().toISOString(),
      source: 'static',
    },
  ])
  render(<ImpactPanel {...baseProps} />)
  await waitFor(() => {
    expect(screen.getByText(/999 calls/)).toBeInTheDocument()
  })
})

/**
 * timeAgo: seconds branch — a date < 60 s ago shows "Xs ago".
 */
test('impact_panel_timeago_shows_seconds_for_recent_date', async () => {
  const recentDate = new Date(Date.now() - 45 * 1000).toISOString()
  fetchImpactAnalysis.mockResolvedValue([
    { service_name: 'svc', call_count: 1, last_seen_at: recentDate, source: 'static' },
  ])
  render(<ImpactPanel {...baseProps} />)
  await waitFor(() => {
    expect(screen.getByText(/\d+s ago/)).toBeInTheDocument()
  })
})

/**
 * timeAgo: minutes branch — a date N minutes ago shows "Nm ago".
 */
test('impact_panel_timeago_shows_minutes_for_date_minutes_old', async () => {
  const fiveMinsAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString()
  fetchImpactAnalysis.mockResolvedValue([
    { service_name: 'svc', call_count: 1, last_seen_at: fiveMinsAgo, source: 'static' },
  ])
  render(<ImpactPanel {...baseProps} />)
  await waitFor(() => {
    expect(screen.getByText(/5m ago/)).toBeInTheDocument()
  })
})

/**
 * timeAgo: hours branch — a date N hours ago shows "Nh ago".
 */
test('impact_panel_timeago_shows_hours_for_date_hours_old', async () => {
  const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString()
  fetchImpactAnalysis.mockResolvedValue([
    { service_name: 'svc', call_count: 1, last_seen_at: threeHoursAgo, source: 'static' },
  ])
  render(<ImpactPanel {...baseProps} />)
  await waitFor(() => {
    expect(screen.getByText(/3h ago/)).toBeInTheDocument()
  })
})

/**
 * timeAgo: days branch — a date N days ago shows "Nd ago".
 */
test('impact_panel_timeago_shows_days_for_date_days_old', async () => {
  const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString()
  fetchImpactAnalysis.mockResolvedValue([
    { service_name: 'svc', call_count: 1, last_seen_at: twoDaysAgo, source: 'static' },
  ])
  render(<ImpactPanel {...baseProps} />)
  await waitFor(() => {
    expect(screen.getByText(/2d ago/)).toBeInTheDocument()
  })
})

/**
 * After the promise resolves the "Loading…" spinner disappears.
 * Empty state is shown in its place.
 */
test('impact_panel_loading_state_clears_after_fetch_resolves', async () => {
  fetchImpactAnalysis.mockResolvedValue([])
  render(<ImpactPanel {...baseProps} />)
  await waitFor(() => {
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
  })
  expect(screen.getByText('No consumers found')).toBeInTheDocument()
})

/**
 * When multiple consumers are returned, every consumer row renders its
 * caller function/file context alongside the service name.
 */
test('impact_panel_renders_every_consumer_when_multiple_returned', async () => {
  fetchImpactAnalysis.mockResolvedValue([
    { service_name: 'order-service', caller_function_name: 'fetchUser', caller_file_path: 'lib/api.js',
      call_count: 10, last_seen_at: new Date().toISOString(), source: 'static' },
    { service_name: 'payment-service', caller_function_name: 'getUser', caller_file_path: 'lib/client.js',
      call_count: 5, last_seen_at: new Date().toISOString(), source: 'logs' },
    { service_name: 'search-service', caller_function_name: 'lookupUser', caller_file_path: 'lib/search.js',
      call_count: 3, last_seen_at: new Date().toISOString(), source: 'static' },
  ])
  render(<ImpactPanel {...baseProps} />)
  await waitFor(() => {
    expect(screen.getByText('fetchUser in lib/api.js (order-service)')).toBeInTheDocument()
    expect(screen.getByText('getUser in lib/client.js (payment-service)')).toBeInTheDocument()
    expect(screen.getByText('lookupUser in lib/search.js (search-service)')).toBeInTheDocument()
  })
})

/**
 * When endpointId prop changes, a fresh fetchImpactAnalysis call fires —
 * once for the initial id, once for the new id.
 */
test('impact_panel_refetches_when_endpointId_prop_changes', async () => {
  fetchImpactAnalysis.mockResolvedValue([])

  const { rerender } = render(<ImpactPanel {...baseProps} endpointId={3} />)
  await waitFor(() => expect(fetchImpactAnalysis).toHaveBeenCalledWith(3))

  rerender(<ImpactPanel {...baseProps} endpointId={7} />)
  await waitFor(() => expect(fetchImpactAnalysis).toHaveBeenCalledWith(7))

  expect(fetchImpactAnalysis).toHaveBeenCalledTimes(2)
})

// ─── GraphPage integration tests (real ImpactPanel, mocked DependencyGraph) ───

/**
 * Clicking an endpoint node (node_type: "endpoint") opens the real ImpactPanel.
 * The "Impact Analysis" label and path appear immediately on render.
 */
test('graph_clicking_endpoint_node_shows_impact_panel', async () => {
  fetchGraph.mockResolvedValue({
    nodes: [{
      id: 'ep:3', node_type: 'endpoint', label: 'delete_item\nDELETE /items/{id}',
      function_name: 'delete_item', method: 'DELETE', path: '/items/{id}',
      file_path: 'routers/items.py', service_name: 'item-service', service_id: 1,
    }],
    edges: [],
  })
  fetchImpactAnalysis.mockResolvedValue([])

  render(<GraphPage />)

  // Wait for DependencyGraph to render after fetchGraph resolves on mount
  await waitFor(() => screen.getByTestId('node-ep:3'))

  fireEvent.click(screen.getByTestId('node-ep:3'))

  // Real ImpactPanel header appears after selectedEndpoint is set
  await waitFor(() => {
    expect(screen.getByText('Impact Analysis')).toBeInTheDocument()
  })
  // method/path/functionName are forwarded from node.data
  expect(screen.getByText('DELETE')).toBeInTheDocument()
  expect(screen.getByText('/items/{id}')).toBeInTheDocument()
  expect(screen.getByText('delete_item')).toBeInTheDocument()
})

/**
 * Clicking a node whose node_type is "caller" (not "endpoint")
 * must not open ImpactPanel.
 */
test('graph_clicking_caller_node_does_not_show_impact_panel', async () => {
  fetchGraph.mockResolvedValue({
    nodes: [{
      id: 'caller:1:lib/api.js:fetchUser', node_type: 'caller', label: 'fetchUser',
      function_name: 'fetchUser', method: null, path: null,
      file_path: 'lib/api.js', service_name: 'order-service', service_id: 1,
    }],
    edges: [],
  })

  render(<GraphPage />)

  await waitFor(() => screen.getByTestId('node-caller:1:lib/api.js:fetchUser'))

  fireEvent.click(screen.getByTestId('node-caller:1:lib/api.js:fetchUser'))

  // handleNodeClick returns early for non-endpoint nodes
  expect(screen.queryByText('Impact Analysis')).not.toBeInTheDocument()
})

/**
 * Clicking the close button (aria-label="Close panel") inside ImpactPanel
 * calls onClose, which sets selectedEndpoint to null, unmounting ImpactPanel.
 */
test('graph_impact_panel_closes_when_close_button_clicked', async () => {
  fetchGraph.mockResolvedValue({
    nodes: [{
      id: 'ep:5', node_type: 'endpoint', label: 'get_user\nGET /users/{id}',
      function_name: 'get_user', method: 'GET', path: '/users/{id}',
      file_path: 'routers/users.py', service_name: 'user-service', service_id: 2,
    }],
    edges: [],
  })
  fetchImpactAnalysis.mockResolvedValue([])

  render(<GraphPage />)

  await waitFor(() => screen.getByTestId('node-ep:5'))

  // Open the panel
  fireEvent.click(screen.getByTestId('node-ep:5'))
  await waitFor(() => screen.getByText('Impact Analysis'))

  // Close it — the ✕ button has aria-label="Close panel"
  fireEvent.click(screen.getByRole('button', { name: /close/i }))

  await waitFor(() => {
    expect(screen.queryByText('Impact Analysis')).not.toBeInTheDocument()
  })
})

// ─── api.js fetchImpactAnalysis error propagation ─────────────────────────────

/**
 * When the FastAPI response is not ok, fetchImpactAnalysis throws an Error
 * whose message is the response body text.
 */
test('fetch_impact_analysis_throws_error_with_response_body_when_not_ok', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    text: jest.fn().mockResolvedValue('Endpoint not found'),
  })

  // jest.requireActual bypasses the jest.mock('@/lib/api') factory and loads
  // the real implementation.  Its import of '@/lib/supabase' resolves to the
  // mocked supabase defined above, so getGitHubToken() returns 'test-token'.
  const { fetchImpactAnalysis: realFetch } = jest.requireActual('@/lib/api')

  await expect(realFetch(99)).rejects.toThrow('Endpoint not found')
})
