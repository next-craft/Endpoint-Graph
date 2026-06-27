'use client'
import { useState } from 'react'
import dynamic from 'next/dynamic'
import AuthGuard from '@/components/AuthGuard'
import RepoInput from '@/components/RepoInput'
import { fetchGraph } from '@/lib/api'

const DependencyGraph = dynamic(
  () => import('@/components/DependencyGraph'),
  { ssr: false }
)

export default function GraphPage() {
  const [nodes, setNodes] = useState([])
  const [edges, setEdges] = useState([])
  const [graphLoading, setGraphLoading] = useState(false)
  const [graphError, setGraphError] = useState(null)

  async function handleAnalysisComplete() {
    setGraphLoading(true)
    setGraphError(null)
    try {
      const graphData = await fetchGraph()
      const rfNodes = graphData.nodes.map((node) => ({
        id: node.id,
        data: { label: node.name },
        position: { x: 0, y: 0 },
      }))
      const rfEdges = graphData.edges.map((edge) => ({
        id: `${edge.source}-${edge.target}-${edge.endpoint_method}-${edge.endpoint_path}`,
        source: edge.source,
        target: edge.target,
        label: `${edge.endpoint_method} ${edge.endpoint_path}`,
      }))
      setNodes(rfNodes)
      setEdges(rfEdges)
    } catch (err) {
      setGraphError(err.message)
    } finally {
      setGraphLoading(false)
    }
  }

  return (
    <AuthGuard>
      <div>
        <RepoInput onAnalysisComplete={handleAnalysisComplete} />
        {graphError && <p>{graphError}</p>}
        {graphLoading && <p>Loading graph…</p>}
        {!graphLoading && nodes.length > 0 && (
          <DependencyGraph
            nodes={nodes}
            edges={edges}
            onNodeClick={(event, node) => console.log('clicked', node)}
          />
        )}
      </div>
    </AuthGuard>
  )
}
