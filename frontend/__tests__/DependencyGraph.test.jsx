import '@testing-library/jest-dom'
import { render, screen, fireEvent } from '@testing-library/react'
import DependencyGraph from '@/components/DependencyGraph'

jest.mock('@xyflow/react', () => ({
  ReactFlow: ({ nodes, onNodeClick, children }) => (
    <div data-testid="react-flow">
      {nodes.map((n) => (
        <div
          key={n.id}
          data-testid={`node-${n.id}`}
          data-parent-id={n.parentId ?? ''}
          data-type={n.type ?? ''}
          data-y={n.position.y}
          onClick={(e) => onNodeClick && onNodeClick(e, n)}
        >
          {n.data.label}
        </div>
      ))}
      {children}
    </div>
  ),
  Background: () => <div data-testid="rf-background" />,
  Controls: () => <div data-testid="rf-controls" />,
  MiniMap: () => <div data-testid="rf-minimap" />,
}))

const endpointNode = {
  id: 'ep:5',
  node_type: 'endpoint',
  label: 'get_user\nGET /users/{id}',
  function_name: 'get_user',
  method: 'GET',
  path: '/users/{id}',
  file_path: 'routers/users.py',
  service_name: 'user-service',
  service_id: 2,
}

const callerNode = {
  id: 'caller:1:lib/api.js:fetchUser',
  node_type: 'caller',
  label: 'fetchUser',
  function_name: 'fetchUser',
  method: null,
  path: null,
  file_path: 'lib/api.js',
  service_name: 'order-service',
  service_id: 1,
}

const oneEdge = [{ source: callerNode.id, target: endpointNode.id, call_count: 5, last_seen_at: '2024-01-01T00:00:00Z' }]

test('test_dependency_graph_renders_endpoint_and_caller_leaf_nodes', () => {
  render(
    <DependencyGraph nodes={[endpointNode, callerNode]} edges={oneEdge} onNodeClick={jest.fn()} />
  )

  expect(screen.getByTestId(`node-${endpointNode.id}`)).toHaveTextContent('get_user')
  expect(screen.getByTestId(`node-${endpointNode.id}`)).toHaveTextContent('GET /users/{id}')
  expect(screen.getByText('fetchUser')).toBeInTheDocument()
  expect(screen.getByTestId('rf-background')).toBeInTheDocument()
  expect(screen.getByTestId('rf-controls')).toBeInTheDocument()
  expect(screen.getByTestId('rf-minimap')).toBeInTheDocument()
})

test('test_dependency_graph_groups_leaf_nodes_under_service_and_file', () => {
  render(
    <DependencyGraph nodes={[endpointNode, callerNode]} edges={oneEdge} onNodeClick={jest.fn()} />
  )

  // Service group nodes exist with plain service_name ids, no parentId
  const serviceGroup = screen.getByTestId('node-user-service')
  expect(serviceGroup).toHaveAttribute('data-type', 'group')
  expect(serviceGroup).toHaveAttribute('data-parent-id', '')

  // File group node id is "{service_name}:{file_path}", parented to the service group
  const fileGroupId = 'user-service:routers/users.py'
  const fileGroup = screen.getByTestId(`node-${fileGroupId}`)
  expect(fileGroup).toHaveAttribute('data-type', 'group')
  expect(fileGroup).toHaveAttribute('data-parent-id', 'user-service')

  // Leaf node is parented to the file group
  const leaf = screen.getByTestId(`node-${endpointNode.id}`)
  expect(leaf).toHaveAttribute('data-parent-id', fileGroupId)
})

test('test_dependency_graph_handles_null_file_path', () => {
  const nodeWithNullFilePath = { ...endpointNode, id: 'ep:9', file_path: null }
  const edges = [{ source: callerNode.id, target: 'ep:9', call_count: 1, last_seen_at: '2024-01-01T00:00:00Z' }]

  render(
    <DependencyGraph nodes={[nodeWithNullFilePath, callerNode]} edges={edges} onNodeClick={jest.fn()} />
  )

  const unknownFileGroup = screen.getByTestId('node-user-service:(unknown)')
  expect(unknownFileGroup).toBeInTheDocument()
  const leaf = screen.getByTestId('node-ep:9')
  expect(leaf).toHaveAttribute('data-parent-id', 'user-service:(unknown)')
})

test('test_dependency_graph_onNodeClick_forwards_full_node_data', () => {
  const onNodeClick = jest.fn()
  render(
    <DependencyGraph nodes={[endpointNode, callerNode]} edges={oneEdge} onNodeClick={onNodeClick} />
  )

  fireEvent.click(screen.getByTestId(`node-${endpointNode.id}`))

  expect(onNodeClick).toHaveBeenCalledTimes(1)
  const [, clickedNode] = onNodeClick.mock.calls[0]
  expect(clickedNode.data.node_type).toBe('endpoint')
  expect(clickedNode.data.method).toBe('GET')
  expect(clickedNode.data.path).toBe('/users/{id}')
  expect(clickedNode.data.function_name).toBe('get_user')
  expect(clickedNode.data.file_path).toBe('routers/users.py')
})

test('test_dependency_graph_tiers_caller_only_above_provider_only_service', () => {
  const callerOnly = {
    ...callerNode,
    id: 'caller:10:lib/a.js:fnA',
    service_name: 'caller-only-svc',
    service_id: 10,
  }
  const providerOnly = {
    ...endpointNode,
    id: 'ep:20',
    service_name: 'provider-only-svc',
    service_id: 20,
  }
  const edges = [{ source: callerOnly.id, target: providerOnly.id, call_count: 1, last_seen_at: '2024-01-01T00:00:00Z' }]

  render(
    <DependencyGraph nodes={[callerOnly, providerOnly]} edges={edges} onNodeClick={jest.fn()} />
  )

  const callerGroupY = Number(screen.getByTestId('node-caller-only-svc').getAttribute('data-y'))
  const providerGroupY = Number(screen.getByTestId('node-provider-only-svc').getAttribute('data-y'))
  expect(callerGroupY).toBeLessThan(providerGroupY)
})

test('test_dependency_graph_tiers_mixed_service_in_middle', () => {
  const callerOnly = {
    ...callerNode,
    id: 'caller:10:lib/a.js:fnA',
    service_name: 'caller-only-svc',
    service_id: 10,
  }
  const providerOnly = {
    ...endpointNode,
    id: 'ep:20',
    service_name: 'provider-only-svc',
    service_id: 20,
  }
  // mixed-svc both calls providerOnly's endpoint and exposes its own endpoint
  const mixedCaller = {
    ...callerNode,
    id: 'caller:30:lib/b.js:fnB',
    service_name: 'mixed-svc',
    service_id: 30,
  }
  const mixedEndpoint = {
    ...endpointNode,
    id: 'ep:40',
    service_name: 'mixed-svc',
    service_id: 30,
  }

  const edges = [
    { source: callerOnly.id, target: providerOnly.id, call_count: 1, last_seen_at: '2024-01-01T00:00:00Z' },
    { source: mixedCaller.id, target: mixedEndpoint.id, call_count: 1, last_seen_at: '2024-01-01T00:00:00Z' },
  ]

  render(
    <DependencyGraph
      nodes={[callerOnly, providerOnly, mixedCaller, mixedEndpoint]}
      edges={edges}
      onNodeClick={jest.fn()}
    />
  )

  const callerGroupY = Number(screen.getByTestId('node-caller-only-svc').getAttribute('data-y'))
  const providerGroupY = Number(screen.getByTestId('node-provider-only-svc').getAttribute('data-y'))
  const mixedGroupY = Number(screen.getByTestId('node-mixed-svc').getAttribute('data-y'))

  expect(mixedGroupY).toBeGreaterThan(callerGroupY)
  expect(mixedGroupY).toBeLessThan(providerGroupY)
})
