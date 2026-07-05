export function filterGraph(nodes, edges, query) {
  const q = query.trim().toLowerCase()
  if (!q) return { visibleNodes: nodes, visibleEdges: edges }

  const visibleNodes = nodes.filter((node) => {
    if (node.node_type !== 'endpoint') return true
    return node.label.toLowerCase().includes(q)
  })

  const visibleNodeIds = new Set(visibleNodes.map((n) => n.id))
  const visibleEdges = edges.filter(
    (edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)
  )

  return { visibleNodes, visibleEdges }
}
