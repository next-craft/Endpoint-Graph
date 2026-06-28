import { render, screen, fireEvent } from '@testing-library/react'
import SearchBar from './SearchBar'

// ── controlled component contract ────────────────────────────────────────────

test('input_displayed_value_is_driven_by_value_prop_not_by_typing', () => {
  // The component is fully controlled: if the parent never updates the prop,
  // the displayed value must stay at the original prop value even after a
  // change event fires.
  const onChange = jest.fn() // intentionally does NOT feed value back
  render(<SearchBar value="abc" onChange={onChange} />)
  const input = screen.getByPlaceholderText('Search endpoints…')
  fireEvent.change(input, { target: { value: 'abcd' } })
  // onChange was called but the prop was NOT re-rendered → still "abc"
  expect(input.value).toBe('abc')
})

test('input_displayed_value_updates_when_value_prop_changes', () => {
  const { rerender } = render(<SearchBar value="abc" onChange={jest.fn()} />)
  const input = screen.getByPlaceholderText('Search endpoints…')
  expect(input.value).toBe('abc')
  rerender(<SearchBar value="xyz" onChange={jest.fn()} />)
  expect(input.value).toBe('xyz')
})

test('input_shows_empty_string_when_value_prop_is_empty_string', () => {
  render(<SearchBar value="" onChange={jest.fn()} />)
  const input = screen.getByPlaceholderText('Search endpoints…')
  expect(input.value).toBe('')
})

// ── onChange argument is the full target value string ────────────────────────

test('onChange_receives_the_complete_string_from_event_target_value', () => {
  // Simulates the user having typed "us" and now adding "e"; the handler must
  // pass the full string "use", not just the new character.
  const onChange = jest.fn()
  render(<SearchBar value="us" onChange={onChange} />)
  const input = screen.getByPlaceholderText('Search endpoints…')
  fireEvent.change(input, { target: { value: 'use' } })
  expect(onChange).toHaveBeenCalledWith('use')
})

test('onChange_called_exactly_once_per_change_event', () => {
  const onChange = jest.fn()
  render(<SearchBar value="" onChange={onChange} />)
  fireEvent.change(screen.getByPlaceholderText('Search endpoints…'), {
    target: { value: 'a' },
  })
  expect(onChange).toHaveBeenCalledTimes(1)
})

test('successive_change_events_produce_correct_consecutive_onChange_calls', () => {
  const onChange = jest.fn()
  render(<SearchBar value="" onChange={onChange} />)
  const input = screen.getByPlaceholderText('Search endpoints…')
  fireEvent.change(input, { target: { value: 'g' } })
  fireEvent.change(input, { target: { value: 'ge' } })
  fireEvent.change(input, { target: { value: 'get' } })
  expect(onChange).toHaveBeenCalledTimes(3)
  expect(onChange).toHaveBeenNthCalledWith(1, 'g')
  expect(onChange).toHaveBeenNthCalledWith(2, 'ge')
  expect(onChange).toHaveBeenNthCalledWith(3, 'get')
})

// ── clear button accessibility ────────────────────────────────────────────────

test('clear_button_has_explicit_aria_label_attribute_set_to_Clear_search', () => {
  render(<SearchBar value="hello" onChange={jest.fn()} />)
  const btn = screen.getByRole('button')
  expect(btn).toHaveAttribute('aria-label', 'Clear search')
})

// ── clear button visibility edge cases ───────────────────────────────────────

test('clear_button_shown_when_value_is_whitespace_only_string', () => {
  // A whitespace-only string is truthy in JS, so the button should render
  render(<SearchBar value="   " onChange={jest.fn()} />)
  expect(screen.getByRole('button', { name: 'Clear search' })).toBeInTheDocument()
})

test('no_button_rendered_at_all_when_value_is_empty_string', () => {
  render(<SearchBar value="" onChange={jest.fn()} />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

// ── clear button click behaviour ─────────────────────────────────────────────

test('clear_button_click_calls_onChange_exactly_once', () => {
  const onChange = jest.fn()
  render(<SearchBar value="some text" onChange={onChange} />)
  fireEvent.click(screen.getByRole('button', { name: 'Clear search' }))
  expect(onChange).toHaveBeenCalledTimes(1)
})

test('clear_button_disappears_after_parent_resets_value_to_empty', () => {
  const { rerender } = render(<SearchBar value="users" onChange={jest.fn()} />)
  expect(screen.getByRole('button', { name: 'Clear search' })).toBeInTheDocument()
  rerender(<SearchBar value="" onChange={jest.fn()} />)
  expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument()
})
