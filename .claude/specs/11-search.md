# Spec 11 — Search Bar

## Goal
Add a `SearchBar.jsx` component that filters the visible endpoint nodes in the React Flow graph as the user types; clearing the search restores all nodes.

## Depends on
Spec 09 (frontend graph), Spec 10 (impact panel). Both must be complete — the graph page must already render nodes and edges.

## Context
The graph page (`app/graph/page.js`) holds `nodes` and `edges` in state and passes them directly to `DependencyGraph`. Node ids use the prefixes `endpoint-` (e.g. `endpoint-3`) and `service-` (e.g. `service-1`). Endpoint node labels look like `GET /users/{id}`. The search feature lives entirely in the frontend — no backend changes, no API calls.

## Files to create
- `frontend/components/SearchBar.jsx` — controlled text input; calls `onChange` prop with current value on every keystroke; has a clear button when non-empty
- `frontend/lib/graphFilter.js` — pure function `filterGraph(nodes, edges, query)` that derives visible nodes and edges from the full lists and a search string; extracted here so it can be unit-tested without rendering the page
- `frontend/components/SearchBar.test.jsx` — Jest tests for the SearchBar component
- `frontend/lib/graphFilter.test.js` — Jest unit tests for the filter logic

## Files to edit
- `frontend/app/graph/page.js` — import `SearchBar` and `filterGraph`, add `search` state, call `filterGraph` in the render body, render `SearchBar` above the canvas, reset `search` on new analysis, pass `visibleNodes`/`visibleEdges` to `DependencyGraph`

## Implementation details

### frontend/lib/graphFilter.js

One exported function: `filterGraph(nodes, edges, query)`

- `nodes` — array of React Flow node objects, each with `id` (string) and `data.label` (string)
- `edges` — array of React Flow edge objects, each with `source` (string) and `target` (string)
- `query` — raw string from the search input (may have leading/trailing whitespace)
- Returns `{ visibleNodes, visibleEdges }`

Logic:
1. `q = query.trim().toLowerCase()`
2. If `q` is empty, return `{ visibleNodes: nodes, visibleEdges: edges }` unchanged
3. Otherwise filter nodes:
   - Nodes whose `id` does NOT start with `'endpoint-'` always pass through (service nodes always visible)
   - Endpoint nodes pass only if `node.data.label.toLowerCase().includes(q)`
4. Build `visibleNodeIds = new Set(visibleNodes.map(n => n.id))`
5. Filter edges: keep only edges where both `edge.source` and `edge.target` are in `visibleNodeIds`
6. Return `{ visibleNodes, visibleEdges }`

```js
export function filterGraph(nodes, edges, query) {
  const q = query.trim().toLowerCase()
  if (!q) return { visibleNodes: nodes, visibleEdges: edges }

  const visibleNodes = nodes.filter((node) => {
    if (!node.id.startsWith('endpoint-')) return true
    return node.data.label.toLowerCase().includes(q)
  })

  const visibleNodeIds = new Set(visibleNodes.map((n) => n.id))
  const visibleEdges = edges.filter(
    (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)
  )

  return { visibleNodes, visibleEdges }
}
```

### frontend/components/SearchBar.jsx

Props: `{ value, onChange }`

- `'use client'` directive at the top
- Renders a `<div>` containing:
  - `<input type="text">` — placeholder `"Search endpoints…"`, value bound to `value` prop, `onChange` calls `onChange(e.target.value)`
  - A clear `<button>` visible only when `value` is non-empty — clicking it calls `onChange('')`
- No internal state — fully controlled
- Tailwind classes for styling: full-width input with a border, rounded corners, padding. Clear button sits inside the input container on the right edge.

```jsx
'use client'
export default function SearchBar({ value, onChange }) {
  return (
    <div className="relative">
      <input
        type="text"
        placeholder="Search endpoints…"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border rounded px-3 py-2 pr-8 text-sm"
      />
      {value && (
        <button
          onClick={() => onChange('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
          aria-label="Clear search"
        >
          ✕
        </button>
      )}
    </div>
  )
}
```

### frontend/app/graph/page.js

**New import at the top:**
```js
import SearchBar from '@/components/SearchBar'
import { filterGraph } from '@/lib/graphFilter'
```

**New state:**
```js
const [search, setSearch] = useState('')
```

**Derive visible nodes and edges** — call `filterGraph` inside the render body (not in useEffect):
```js
const { visibleNodes, visibleEdges } = filterGraph(nodes, edges, search)
```

**Reset search on new analysis** — inside `handleAnalysisComplete`, add alongside the existing `setSelectedEndpoint(null)`:
```js
setSearch('')
```

**Render `SearchBar`** between `RepoInput` and the graph canvas, guarded by `nodes.length > 0` (same guard as `DependencyGraph`):
```jsx
{nodes.length > 0 && (
  <div className="px-4 py-2">
    <SearchBar value={search} onChange={setSearch} />
  </div>
)}
```

**Pass derived lists to `DependencyGraph`** — the existing `DependencyGraph` block already has a `!graphLoading && nodes.length > 0` guard; keep that guard, just replace the props:
```jsx
<DependencyGraph
  nodes={visibleNodes}
  edges={visibleEdges}
  onNodeClick={handleNodeClick}
/>
```

## Test cases

**Testing setup:** `@testing-library/react` (v16) and `@testing-library/jest-dom` are already in `devDependencies`. `next/jest` (already configured in `jest.config.js`) handles CSS imports automatically — no `moduleNameMapper` changes are needed for `@xyflow/react/dist/style.css`. Use `fireEvent` from `@testing-library/react` for all event simulation (not `userEvent` — `@testing-library/user-event` is not installed).

---

### frontend/components/SearchBar.test.jsx

Import: `import { render, screen, fireEvent } from '@testing-library/react'`

- `renders_input_with_placeholder` — renders `<SearchBar value="" onChange={jest.fn()} />`, asserts `screen.getByPlaceholderText('Search endpoints…')` is in the document
- `calls_onChange_on_keystroke` — renders with `value=""` and an `onChange` spy; calls `fireEvent.change(input, { target: { value: 'users' } })`; asserts spy was called with `'users'`
- `clear_button_hidden_when_empty` — renders with `value=""`, asserts `screen.queryByRole('button', { name: 'Clear search' })` is `null`
- `clear_button_visible_when_non_empty` — renders with `value="users"`, asserts `screen.getByRole('button', { name: 'Clear search' })` is in the document
- `clear_button_calls_onChange_with_empty_string` — renders with `value="users"` and an `onChange` spy; clicks the clear button via `fireEvent.click`; asserts spy was called with `''`

---

### frontend/lib/graphFilter.test.js

Import: `import { filterGraph } from './graphFilter'`

Helper data used across tests:
```js
const serviceNode = { id: 'service-1', data: { label: 'user-service' } }
const endpointA   = { id: 'endpoint-1', data: { label: 'GET /users/{id}' } }
const endpointB   = { id: 'endpoint-2', data: { label: 'POST /orders/create' } }
const edge1 = { id: 'e1', source: 'service-1', target: 'endpoint-1' }
const edge2 = { id: 'e2', source: 'service-1', target: 'endpoint-2' }
const nodes = [serviceNode, endpointA, endpointB]
const edges = [edge1, edge2]
```

- `empty_query_returns_all_nodes_and_edges` — calls `filterGraph(nodes, edges, '')`, asserts `visibleNodes` has length 3 and `visibleEdges` has length 2
- `whitespace_only_query_returns_all_nodes_and_edges` — calls `filterGraph(nodes, edges, '   ')`, asserts same as above
- `matching_query_keeps_matching_endpoint_and_all_service_nodes` — calls `filterGraph(nodes, edges, 'users')`, asserts `visibleNodes` contains `serviceNode` and `endpointA` but not `endpointB`
- `non_matching_endpoint_nodes_are_hidden` — calls `filterGraph(nodes, edges, 'payments')`, asserts `visibleNodes` contains only `serviceNode` (no endpoints), length is 1
- `edges_to_hidden_endpoint_nodes_are_removed` — calls `filterGraph(nodes, edges, 'users')`, asserts `visibleEdges` contains `edge1` but not `edge2`
- `clearing_query_restores_all_nodes_and_edges` — calls `filterGraph(nodes, edges, 'users')` then `filterGraph(nodes, edges, '')`, asserts the second call returns all 3 nodes and 2 edges

## Done when

- [ ] `frontend/lib/graphFilter.js` exists and exports `filterGraph(nodes, edges, query)` returning `{ visibleNodes, visibleEdges }`
- [ ] `frontend/components/SearchBar.jsx` exists and is a fully controlled component (`value`/`onChange` props, no internal state) with a clear button that appears only when `value` is non-empty
- [ ] `frontend/app/graph/page.js` imports both `SearchBar` and `filterGraph`, has `search` state, calls `filterGraph` in the render body, renders `SearchBar` above the canvas when `nodes.length > 0`, resets `search` to `''` inside `handleAnalysisComplete`, passes `visibleNodes`/`visibleEdges` to `DependencyGraph`
- [ ] Typing a partial path (e.g. `'users'`) hides endpoint nodes whose label does not include that substring; service nodes always remain visible
- [ ] Edges connected to a hidden endpoint node are also hidden
- [ ] Clearing the search (empty string or clicking the clear button) restores all nodes and edges
- [ ] `frontend/components/SearchBar.test.jsx` exists with all five tests passing
- [ ] `frontend/lib/graphFilter.test.js` exists with all six tests passing
- [ ] No TypeScript — files are `.jsx` / `.js`
- [ ] No hardcoded credentials anywhere
- [ ] Follows CLAUDE.md conventions (no inline fetch, no TypeScript, Tailwind v4 utility classes)
