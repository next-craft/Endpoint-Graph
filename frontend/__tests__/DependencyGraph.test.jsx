import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import DependencyGraph from '@/components/DependencyGraph'

jest.mock('@xyflow/react', () => ({
  ReactFlow: ({ nodes, children }) => (
    <div data-testid="react-flow">
      {nodes.map((n) => (
        <div key={n.id} data-testid="rf-node">
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

test('test_dependency_graph_renders_nodes', () => {
  const nodes = [
    { id: '1', data: { label: 'order-service' }, position: { x: 0, y: 0 } },
  ]
  const edges = []

  render(
    <DependencyGraph nodes={nodes} edges={edges} onNodeClick={jest.fn()} />
  )

  expect(screen.getByText('order-service')).toBeInTheDocument()
  expect(screen.getByTestId('rf-background')).toBeInTheDocument()
  expect(screen.getByTestId('rf-controls')).toBeInTheDocument()
  expect(screen.getByTestId('rf-minimap')).toBeInTheDocument()
})
