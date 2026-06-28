import { filterGraph } from './graphFilter'

const serviceNode = { id: 'service-1', data: { label: 'user-service' } }
const endpointA   = { id: 'endpoint-1', data: { label: 'GET /users/{id}' } }
const endpointB   = { id: 'endpoint-2', data: { label: 'POST /orders/create' } }
const edge1 = { id: 'e1', source: 'service-1', target: 'endpoint-1' }
const edge2 = { id: 'e2', source: 'service-1', target: 'endpoint-2' }
const nodes = [serviceNode, endpointA, endpointB]
const edges = [edge1, edge2]

test('empty_query_returns_all_nodes_and_edges', () => {
  const { visibleNodes, visibleEdges } = filterGraph(nodes, edges, '')
  expect(visibleNodes).toHaveLength(3)
  expect(visibleEdges).toHaveLength(2)
})

test('whitespace_only_query_returns_all_nodes_and_edges', () => {
  const { visibleNodes, visibleEdges } = filterGraph(nodes, edges, '   ')
  expect(visibleNodes).toHaveLength(3)
  expect(visibleEdges).toHaveLength(2)
})

test('matching_query_keeps_matching_endpoint_and_all_service_nodes', () => {
  const { visibleNodes } = filterGraph(nodes, edges, 'users')
  expect(visibleNodes).toContain(serviceNode)
  expect(visibleNodes).toContain(endpointA)
  expect(visibleNodes).not.toContain(endpointB)
})

test('non_matching_endpoint_nodes_are_hidden', () => {
  const { visibleNodes } = filterGraph(nodes, edges, 'payments')
  expect(visibleNodes).toHaveLength(1)
  expect(visibleNodes[0]).toBe(serviceNode)
})

test('edges_to_hidden_endpoint_nodes_are_removed', () => {
  const { visibleEdges } = filterGraph(nodes, edges, 'users')
  expect(visibleEdges).toContain(edge1)
  expect(visibleEdges).not.toContain(edge2)
})

test('clearing_query_restores_all_nodes_and_edges', () => {
  filterGraph(nodes, edges, 'users')
  const { visibleNodes, visibleEdges } = filterGraph(nodes, edges, '')
  expect(visibleNodes).toHaveLength(3)
  expect(visibleEdges).toHaveLength(2)
})
