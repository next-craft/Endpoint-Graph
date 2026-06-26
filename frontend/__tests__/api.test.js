import '@testing-library/jest-dom'
import {
  triggerAnalysis,
  fetchGraph,
  fetchServices,
  fetchImpactAnalysis,
} from '@/lib/api'

jest.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: jest.fn(),
    },
  },
}))

const { supabase } = require('@/lib/supabase')

const SESSION_WITH_TOKEN = {
  data: { session: { provider_token: 'test-token' } },
}

beforeEach(() => {
  jest.clearAllMocks()
  process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8000'
  supabase.auth.getSession.mockResolvedValue(SESSION_WITH_TOKEN)
  global.fetch = jest.fn().mockResolvedValue({
    json: jest.fn().mockResolvedValue({}),
  })
})

test('test_trigger_analysis_sends_correct_request', async () => {
  await triggerAnalysis('github.com/user/repo')

  expect(global.fetch).toHaveBeenCalledWith(
    'http://localhost:8000/analyze',
    expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'X-GitHub-Token': 'test-token',
      }),
      body: JSON.stringify({ repo_url: 'github.com/user/repo' }),
    })
  )
})

test('test_fetch_graph_sends_correct_request', async () => {
  await fetchGraph()

  expect(global.fetch).toHaveBeenCalledWith(
    'http://localhost:8000/graph',
    expect.objectContaining({
      headers: expect.objectContaining({
        'X-GitHub-Token': 'test-token',
      }),
    })
  )
})

test('test_fetch_services_sends_correct_request', async () => {
  await fetchServices()

  expect(global.fetch).toHaveBeenCalledWith(
    'http://localhost:8000/services',
    expect.objectContaining({
      headers: expect.objectContaining({
        'X-GitHub-Token': 'test-token',
      }),
    })
  )
})

test('test_fetch_impact_analysis_sends_correct_request', async () => {
  await fetchImpactAnalysis(42)

  expect(global.fetch).toHaveBeenCalledWith(
    'http://localhost:8000/endpoints/42/impact-analysis',
    expect.objectContaining({
      headers: expect.objectContaining({
        'X-GitHub-Token': 'test-token',
      }),
    })
  )
})
