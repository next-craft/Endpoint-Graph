import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import AuthGuard from '@/components/AuthGuard'

const mockReplace = jest.fn()

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace }),
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

test('test_authguard_redirects_unauthenticated', async () => {
  supabase.auth.getSession.mockResolvedValue({ data: { session: null } })

  render(
    <AuthGuard>
      <div>protected</div>
    </AuthGuard>
  )

  await waitFor(() => {
    expect(mockReplace).toHaveBeenCalledWith('/login')
  })
  expect(screen.queryByText('protected')).not.toBeInTheDocument()
})

test('test_authguard_renders_children_when_authenticated', async () => {
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
  expect(mockReplace).not.toHaveBeenCalled()
})
