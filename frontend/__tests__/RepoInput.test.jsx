import '@testing-library/jest-dom'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import RepoInput from '@/components/RepoInput'

jest.mock('@/lib/api', () => ({
  triggerAnalysis: jest.fn(),
}))

const { triggerAnalysis } = require('@/lib/api')

beforeEach(() => {
  jest.clearAllMocks()
})

test('test_repoinput_calls_triggerAnalysis_on_button_click', async () => {
  triggerAnalysis.mockResolvedValue({})
  const onAnalysisComplete = jest.fn()

  render(<RepoInput onAnalysisComplete={onAnalysisComplete} />)

  fireEvent.change(screen.getByPlaceholderText('github.com/owner/repo'), {
    target: { value: 'github.com/user/repo' },
  })
  fireEvent.click(screen.getByText('Analyze'))

  await waitFor(() => {
    expect(triggerAnalysis).toHaveBeenCalledWith('github.com/user/repo')
  })
})

test('test_repoinput_calls_onAnalysisComplete_after_success', async () => {
  triggerAnalysis.mockResolvedValue({})
  const onAnalysisComplete = jest.fn()

  render(<RepoInput onAnalysisComplete={onAnalysisComplete} />)

  fireEvent.click(screen.getByText('Analyze'))

  await waitFor(() => {
    expect(onAnalysisComplete).toHaveBeenCalledTimes(1)
  })
})

test('test_repoinput_shows_error_on_failure', async () => {
  triggerAnalysis.mockRejectedValue(new Error('clone failed'))
  const onAnalysisComplete = jest.fn()

  render(<RepoInput onAnalysisComplete={onAnalysisComplete} />)

  fireEvent.click(screen.getByText('Analyze'))

  await waitFor(() => {
    expect(screen.getByText('clone failed')).toBeInTheDocument()
  })
  expect(onAnalysisComplete).not.toHaveBeenCalled()
})

test('test_repoinput_disables_button_while_loading', async () => {
  triggerAnalysis.mockReturnValue(new Promise(() => {}))

  render(<RepoInput onAnalysisComplete={jest.fn()} />)

  fireEvent.click(screen.getByText('Analyze'))

  await waitFor(() => {
    expect(screen.getByText('Analyze')).toBeDisabled()
  })
})
