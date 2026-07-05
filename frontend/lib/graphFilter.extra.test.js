import { filterGraph } from './graphFilter'

// ── fixtures ────────────────────────────────────────────────────────────────
const serviceA = { id: 'caller-1', node_type: 'caller', label: 'user-service' }
const serviceB = { id: 'caller-2', node_type: 'caller', label: 'order-service' }
const endpointGet  = { id: 'ep:1', node_type: 'endpoint', label: 'GET /users/{id}' }
const endpointPost = { id: 'ep:2', node_type: 'endpoint', label: 'POST /orders/create' }
const endpointPut  = { id: 'ep:3', node_type: 'endpoint', label: 'PUT /users/{id}/profile' }

const edgeServiceToService = { id: 'e0', source: 'caller-1', target: 'caller-2' }
const edgeToGetEndpoint    = { id: 'e1', source: 'caller-1', target: 'ep:1' }
const edgeToPostEndpoint   = { id: 'e2', source: 'caller-2', target: 'ep:2' }
const edgeEndpointToEndpoint = { id: 'e3', source: 'ep:1', target: 'ep:3' }

// ── case-insensitive matching ────────────────────────────────────────────────

test('uppercase_query_matches_lowercase_path_in_label', () => {
  const nodes = [serviceA, endpointGet, endpointPost]
  const edges = [edgeToGetEndpoint, edgeToPostEndpoint]
  const { visibleNodes } = filterGraph(nodes, edges, 'USERS')
  expect(visibleNodes).toContain(endpointGet)
  expect(visibleNodes).not.toContain(endpointPost)
})

test('mixed_case_query_matches_label_case_insensitively', () => {
  const nodes = [serviceA, endpointGet]
  const { visibleNodes } = filterGraph(nodes, [], 'GeT /UsErS')
  expect(visibleNodes).toContain(endpointGet)
})

// ── partial match at different positions in the label ────────────────────────

test('query_matching_method_prefix_of_label_filters_correctly', () => {
  // "GET" appears at the very start of the label; POST endpoint should not match
  const nodes = [serviceA, endpointGet, endpointPost]
  const { visibleNodes } = filterGraph(nodes, [], 'GET')
  expect(visibleNodes).toContain(endpointGet)
  expect(visibleNodes).not.toContain(endpointPost)
})

test('query_matching_end_of_label_filters_correctly', () => {
  // '{id}' appears at the end of 'GET /users/{id}' but not in 'POST /orders/create'
  const nodes = [serviceA, endpointGet, endpointPost]
  const { visibleNodes } = filterGraph(nodes, [], '{id}')
  expect(visibleNodes).toContain(endpointGet)
  expect(visibleNodes).not.toContain(endpointPost)
})

test('post_query_matches_only_post_endpoint', () => {
  const nodes = [serviceA, endpointGet, endpointPost]
  const { visibleNodes } = filterGraph(nodes, [], 'post')
  expect(visibleNodes).toContain(endpointPost)
  expect(visibleNodes).not.toContain(endpointGet)
})

// ── multiple endpoints matching ──────────────────────────────────────────────

test('query_that_matches_multiple_endpoint_labels_keeps_all_of_them', () => {
  // "users" appears in both 'GET /users/{id}' and 'PUT /users/{id}/profile'
  const nodes = [serviceA, endpointGet, endpointPut, endpointPost]
  const { visibleNodes } = filterGraph(nodes, [], 'users')
  expect(visibleNodes).toContain(endpointGet)
  expect(visibleNodes).toContain(endpointPut)
  expect(visibleNodes).not.toContain(endpointPost)
})

// ── exact label match ────────────────────────────────────────────────────────

test('query_that_exactly_matches_full_label_keeps_that_endpoint', () => {
  const nodes = [serviceA, endpointGet, endpointPost]
  const { visibleNodes } = filterGraph(nodes, [], 'GET /users/{id}')
  expect(visibleNodes).toContain(endpointGet)
  expect(visibleNodes).not.toContain(endpointPost)
})

// ── empty arrays ─────────────────────────────────────────────────────────────

test('empty_nodes_array_returns_empty_results_without_error', () => {
  const { visibleNodes, visibleEdges } = filterGraph([], [], 'users')
  expect(visibleNodes).toHaveLength(0)
  expect(visibleEdges).toHaveLength(0)
})

test('empty_edges_array_returns_empty_edges_when_query_matches', () => {
  const nodes = [serviceA, endpointGet]
  const { visibleEdges } = filterGraph(nodes, [], 'users')
  expect(visibleEdges).toHaveLength(0)
})

// ── multiple non-endpoint (caller) nodes all pass through ────────────────────

test('all_non_endpoint_nodes_pass_through_regardless_of_query', () => {
  const nodes = [serviceA, serviceB, endpointGet, endpointPost]
  // query "xyz" matches no endpoint labels; both caller nodes still visible
  const { visibleNodes } = filterGraph(nodes, [], 'xyz')
  expect(visibleNodes).toContain(serviceA)
  expect(visibleNodes).toContain(serviceB)
  expect(visibleNodes).not.toContain(endpointGet)
  expect(visibleNodes).not.toContain(endpointPost)
})

// ── non-endpoint node passes through even when its label doesn't match ───────

test('non_endpoint_node_always_passes_through_independent_of_its_label', () => {
  // 'user-service' label does not contain 'orders', but the caller node still passes
  const nodes = [serviceA, endpointPost]
  const { visibleNodes } = filterGraph(nodes, [], 'orders')
  expect(visibleNodes).toContain(serviceA)
})

// ── caller-to-caller edge survives when endpoints are filtered out ──────────

test('non_endpoint_to_non_endpoint_edge_kept_when_query_filters_out_all_endpoints', () => {
  const nodes = [serviceA, serviceB, endpointGet]
  const edges = [edgeServiceToService, edgeToGetEndpoint]
  // "nomatch" filters out endpointGet; both caller nodes remain → their edge stays
  const { visibleEdges } = filterGraph(nodes, edges, 'nomatch')
  expect(visibleEdges).toContain(edgeServiceToService)
  expect(visibleEdges).not.toContain(edgeToGetEndpoint)
})

// ── edge between two endpoints, both matching ────────────────────────────────

test('edge_between_two_matching_endpoints_is_kept', () => {
  // ep:1 (GET /users/{id}) and ep:3 (PUT /users/{id}/profile) both contain "users"
  const nodes = [serviceA, endpointGet, endpointPut, endpointPost]
  const edges = [edgeEndpointToEndpoint, edgeToPostEndpoint]
  const { visibleEdges } = filterGraph(nodes, edges, 'users')
  expect(visibleEdges).toContain(edgeEndpointToEndpoint)
  expect(visibleEdges).not.toContain(edgeToPostEndpoint)
})

// ── edge removed when source endpoint is filtered ────────────────────────────

test('edge_removed_when_source_endpoint_does_not_match_query', () => {
  // edgeEndpointToEndpoint: source=ep:1 (GET /users/{id}), target=ep:3 (PUT /users/{id}/profile)
  // query "orders" matches neither → edge must be removed
  const nodes = [serviceA, endpointGet, endpointPut]
  const edges = [edgeEndpointToEndpoint]
  const { visibleEdges } = filterGraph(nodes, edges, 'orders')
  expect(visibleEdges).toHaveLength(0)
})
