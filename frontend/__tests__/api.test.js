import '@testing-library/jest-dom'
import {
  triggerAnalysis,
  fetchGraph,
  fetchServices,
  fetchImpactAnalysis,
  fetchUserRepos,
  deleteService,
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
  data: { session: { provider_token: 'test-token', access_token: 'test-jwt' } },
}

beforeEach(() => {
  jest.clearAllMocks()
  process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8000'
  supabase.auth.getSession.mockResolvedValue(SESSION_WITH_TOKEN)
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
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
        'Authorization': 'Bearer test-jwt',
      }),
      body: JSON.stringify({ repo_url: 'github.com/user/repo' }),
    })
  )
})

test('test_fetch_graph_sends_correct_request', async () => {
  await fetchGraph('owner/repo')

  expect(global.fetch).toHaveBeenCalledWith(
    'http://localhost:8000/graph?repo_id=owner%2Frepo',
    expect.objectContaining({
      headers: expect.objectContaining({
        'X-GitHub-Token': 'test-token',
        'Authorization': 'Bearer test-jwt',
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
        'Authorization': 'Bearer test-jwt',
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
        'Authorization': 'Bearer test-jwt',
      }),
    })
  )
})

test('test_fetch_impact_analysis_throws_on_non_ok_response', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    text: jest.fn().mockResolvedValue('Not Found'),
  })

  await expect(fetchImpactAnalysis(99)).rejects.toThrow('Not Found')
})

test('test_fetch_user_repos_sends_get_request_to_repos_with_both_auth_headers', async () => {
  await fetchUserRepos()

  expect(global.fetch).toHaveBeenCalledWith(
    'http://localhost:8000/repos',
    expect.objectContaining({
      headers: expect.objectContaining({
        'X-GitHub-Token': 'test-token',
        'Authorization': 'Bearer test-jwt',
      }),
    })
  )
})

test('test_fetch_user_repos_throws_on_non_ok_response', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    text: jest.fn().mockResolvedValue('Unauthorized'),
  })

  await expect(fetchUserRepos()).rejects.toThrow('Unauthorized')
})

test('test_delete_service_sends_delete_request_to_correct_url_with_both_auth_headers', async () => {
  await deleteService(7)

  expect(global.fetch).toHaveBeenCalledWith(
    'http://localhost:8000/services/7',
    expect.objectContaining({
      method: 'DELETE',
      headers: expect.objectContaining({
        'X-GitHub-Token': 'test-token',
        'Authorization': 'Bearer test-jwt',
      }),
    })
  )
})

test('test_delete_service_throws_on_non_ok_response', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    text: jest.fn().mockResolvedValue('Service not found'),
  })

  await expect(deleteService(999)).rejects.toThrow('Service not found')
})

test('test_get_auth_headers_throws_when_provider_token_is_missing', async () => {
  const { supabase } = require('@/lib/supabase')
  supabase.auth.getSession.mockResolvedValue({
    data: { session: { provider_token: null, access_token: 'test-jwt' } },
  })

  await expect(triggerAnalysis('https://github.com/user/repo')).rejects.toThrow(
    'Session expired — please log in again'
  )
})

test('test_get_auth_headers_throws_when_access_token_is_missing', async () => {
  const { supabase } = require('@/lib/supabase')
  supabase.auth.getSession.mockResolvedValue({
    data: { session: { provider_token: 'test-token', access_token: null } },
  })

  await expect(triggerAnalysis('https://github.com/user/repo')).rejects.toThrow(
    'Session expired — please log in again'
  )
})

test('test_get_auth_headers_throws_when_session_is_null', async () => {
  const { supabase } = require('@/lib/supabase')
  supabase.auth.getSession.mockResolvedValue({
    data: { session: null },
  })

  await expect(fetchUserRepos()).rejects.toThrow('Session expired — please log in again')
})
