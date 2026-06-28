import { render, screen, fireEvent } from '@testing-library/react'
import SearchBar from './SearchBar'

test('renders_input_with_placeholder', () => {
  render(<SearchBar value="" onChange={jest.fn()} />)
  expect(screen.getByPlaceholderText('Search endpoints…')).toBeInTheDocument()
})

test('calls_onChange_on_keystroke', () => {
  const onChange = jest.fn()
  render(<SearchBar value="" onChange={onChange} />)
  const input = screen.getByPlaceholderText('Search endpoints…')
  fireEvent.change(input, { target: { value: 'users' } })
  expect(onChange).toHaveBeenCalledWith('users')
})

test('clear_button_hidden_when_empty', () => {
  render(<SearchBar value="" onChange={jest.fn()} />)
  expect(screen.queryByRole('button', { name: 'Clear search' })).toBeNull()
})

test('clear_button_visible_when_non_empty', () => {
  render(<SearchBar value="users" onChange={jest.fn()} />)
  expect(screen.getByRole('button', { name: 'Clear search' })).toBeInTheDocument()
})

test('clear_button_calls_onChange_with_empty_string', () => {
  const onChange = jest.fn()
  render(<SearchBar value="users" onChange={onChange} />)
  fireEvent.click(screen.getByRole('button', { name: 'Clear search' }))
  expect(onChange).toHaveBeenCalledWith('')
})
