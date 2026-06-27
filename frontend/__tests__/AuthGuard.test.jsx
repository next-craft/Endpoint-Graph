import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import AuthGuard from '@/components/AuthGuard'

const mockPush = jest.fn()

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}))

jest.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: jest.fn(),
    },
  },
}))

const { supabase } = require('@/lib/supabase')

beforeEach(() => {
  jest.clearAllMocks()
})

test('test_authguard_redirects_when_no_session', async () => {
  supabase.auth.getSession.mockResolvedValue({ data: { session: null } })

  render(
    <AuthGuard>
      <div>protected</div>
    </AuthGuard>
  )

  await waitFor(() => {
    expect(mockPush).toHaveBeenCalledWith('/login')
  })
  expect(screen.queryByText('protected')).not.toBeInTheDocument()
})

test('test_authguard_renders_children_when_session_exists', async () => {
  supabase.auth.getSession.mockResolvedValue({
    data: { session: { provider_token: 'tok' } },
  })

  render(
    <AuthGuard>
      <div>protected</div>
    </AuthGuard>
  )

  await waitFor(() => {
    expect(screen.getByText('protected')).toBeInTheDocument()
  })
  expect(mockPush).not.toHaveBeenCalled()
})
