import '@testing-library/jest-dom'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ImpactPanel from '@/components/ImpactPanel'

jest.mock('@/lib/api', () => ({
  fetchImpactAnalysis: jest.fn(),
}))

const { fetchImpactAnalysis } = require('@/lib/api')

const defaultProps = {
  endpointId: 1,
  method: 'GET',
  path: '/users/{id}',
  functionName: 'get_user',
  onClose: jest.fn(),
}

beforeEach(() => {
  jest.clearAllMocks()
})

test('test_impact_panel_shows_loading_state', () => {
  fetchImpactAnalysis.mockReturnValue(new Promise(() => {}))
  render(<ImpactPanel {...defaultProps} />)
  expect(screen.getByText('Loading…')).toBeInTheDocument()
})

test('test_impact_panel_shows_consumer_list', async () => {
  fetchImpactAnalysis.mockResolvedValue([
    {
      service_name: 'order-service',
      caller_function_name: 'fetchUser',
      caller_file_path: 'lib/api.js',
      call_count: 42,
      last_seen_at: new Date().toISOString(),
      source: 'static',
    },
  ])
  render(<ImpactPanel {...defaultProps} />)
  await waitFor(() => {
    expect(screen.getByText('fetchUser in lib/api.js (order-service)')).toBeInTheDocument()
    expect(screen.getByText(/42 calls/)).toBeInTheDocument()
  })
})

test('test_impact_panel_consumer_row_falls_back_when_caller_context_missing', async () => {
  fetchImpactAnalysis.mockResolvedValue([
    {
      service_name: 'order-service',
      caller_function_name: null,
      caller_file_path: null,
      call_count: 3,
      last_seen_at: new Date().toISOString(),
      source: 'static',
    },
  ])
  render(<ImpactPanel {...defaultProps} />)
  await waitFor(() => {
    expect(screen.getByText('unknown in unknown file (order-service)')).toBeInTheDocument()
  })
})

test('test_impact_panel_shows_function_name_above_method_path', () => {
  fetchImpactAnalysis.mockReturnValue(new Promise(() => {}))
  render(<ImpactPanel {...defaultProps} />)
  expect(screen.getByText('get_user')).toBeInTheDocument()
  expect(screen.getByText('GET')).toBeInTheDocument()
  expect(screen.getByText('/users/{id}')).toBeInTheDocument()
})

test('test_impact_panel_shows_empty_state', async () => {
  fetchImpactAnalysis.mockResolvedValue([])
  render(<ImpactPanel {...defaultProps} />)
  await waitFor(() => {
    expect(screen.getByText('No consumers found')).toBeInTheDocument()
  })
})

test('test_impact_panel_shows_error_state', async () => {
  fetchImpactAnalysis.mockRejectedValue(new Error('network error'))
  render(<ImpactPanel {...defaultProps} />)
  await waitFor(() => {
    expect(screen.getByText('Failed to load consumers.')).toBeInTheDocument()
  })
})

test('test_impact_panel_calls_onClose_on_button_click', async () => {
  fetchImpactAnalysis.mockResolvedValue([])
  const onClose = jest.fn()
  render(<ImpactPanel {...defaultProps} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: /close/i }))
  expect(onClose).toHaveBeenCalledTimes(1)
})

test('test_impact_panel_refetches_when_endpointId_changes', async () => {
  fetchImpactAnalysis.mockResolvedValue([])

  const { rerender } = render(<ImpactPanel {...defaultProps} endpointId={1} />)
  await waitFor(() => expect(fetchImpactAnalysis).toHaveBeenCalledWith(1))

  rerender(<ImpactPanel {...defaultProps} endpointId={2} />)
  await waitFor(() => expect(fetchImpactAnalysis).toHaveBeenCalledWith(2))

  expect(fetchImpactAnalysis).toHaveBeenCalledTimes(2)
})
