import '@testing-library/jest-dom'

// jsdom's test environment doesn't expose the global structuredClone that
// @dagrejs/dagre relies on internally — polyfill it for the test environment only.
if (typeof global.structuredClone !== 'function') {
  global.structuredClone = (value) => JSON.parse(JSON.stringify(value))
}
