/**
 * Spec-10 tests for ImpactPanel, GraphPage node-click wiring, and
 * fetchImpactAnalysis error propagation in api.js.
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
        data: { session: { provider_token: 'test-token' } },
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
 * MockDependencyGraph renders each node as a clickable div that fires
 * onNodeClick with the full node object — same shape GraphPage builds.
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
            onClick={(e) => onNodeClick && onNodeClick(e, n)}
          >
            {n.data.label}
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
  endpointLabel: 'GET /users/{id}',
  onClose: jest.fn(),
}

/**
 * endpointLabel prop is rendered inside the h2 heading element.
 */
test('impact_panel_renders_endpointLabel_in_h2_heading', async () => {
  fetchImpactAnalysis.mockResolvedValue([])
  render(<ImpactPanel {...baseProps} endpointLabel="POST /orders/create" />)
  expect(
    screen.getByRole('heading', { name: 'POST /orders/create' })
  ).toBeInTheDocument()
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
  expect(screen.getByText('No consumers found.')).toBeInTheDocument()
})

/**
 * When multiple consumers are returned, every service_name is rendered.
 */
test('impact_panel_renders_every_consumer_when_multiple_returned', async () => {
  fetchImpactAnalysis.mockResolvedValue([
    { service_name: 'order-service', call_count: 10, last_seen_at: new Date().toISOString(), source: 'static' },
    { service_name: 'payment-service', call_count: 5, last_seen_at: new Date().toISOString(), source: 'logs' },
    { service_name: 'search-service', call_count: 3, last_seen_at: new Date().toISOString(), source: 'static' },
  ])
  render(<ImpactPanel {...baseProps} />)
  await waitFor(() => {
    expect(screen.getByText('order-service')).toBeInTheDocument()
    expect(screen.getByText('payment-service')).toBeInTheDocument()
    expect(screen.getByText('search-service')).toBeInTheDocument()
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
 * Clicking a node whose id starts with "endpoint-" opens the real ImpactPanel.
 * The heading and "Impact Analysis" label appear immediately on render.
 */
test('graph_clicking_endpoint_node_shows_impact_panel', async () => {
  fetchGraph.mockResolvedValue({
    nodes: [{ id: 'endpoint-3', name: 'DELETE /items/{id}' }],
    edges: [],
  })
  fetchImpactAnalysis.mockResolvedValue([])

  render(<GraphPage />)

  // Wait for DependencyGraph to render after fetchGraph resolves on mount
  await waitFor(() => screen.getByText('DELETE /items/{id}'))

  fireEvent.click(screen.getByText('DELETE /items/{id}'))

  // Real ImpactPanel header appears after selectedEndpoint is set
  await waitFor(() => {
    expect(screen.getByText('Impact Analysis')).toBeInTheDocument()
  })
  // endpointLabel is forwarded from node.data.label → appears in the h2
  expect(screen.getByRole('heading', { name: 'DELETE /items/{id}' })).toBeInTheDocument()
})

/**
 * Clicking a node whose id does NOT start with "endpoint-" (a service node)
 * must not open ImpactPanel.
 */
test('graph_clicking_service_node_does_not_show_impact_panel', async () => {
  fetchGraph.mockResolvedValue({
    nodes: [{ id: '1', name: 'order-service' }],
    edges: [],
  })

  render(<GraphPage />)

  await waitFor(() => screen.getByText('order-service'))

  fireEvent.click(screen.getByText('order-service'))

  // handleNodeClick returns early for non-endpoint nodes
  expect(screen.queryByText('Impact Analysis')).not.toBeInTheDocument()
})

/**
 * Clicking the close button (aria-label="Close") inside ImpactPanel calls
 * onClose, which sets selectedEndpoint to null, unmounting ImpactPanel.
 */
test('graph_impact_panel_closes_when_close_button_clicked', async () => {
  fetchGraph.mockResolvedValue({
    nodes: [{ id: 'endpoint-5', name: 'GET /users/{id}' }],
    edges: [],
  })
  fetchImpactAnalysis.mockResolvedValue([])

  render(<GraphPage />)

  await waitFor(() => screen.getByText('GET /users/{id}'))

  // Open the panel
  fireEvent.click(screen.getByText('GET /users/{id}'))
  await waitFor(() => screen.getByText('Impact Analysis'))

  // Close it — the ✕ button has aria-label="Close"
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
