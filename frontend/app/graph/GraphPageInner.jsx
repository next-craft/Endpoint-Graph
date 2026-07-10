'use client'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import dynamic from 'next/dynamic'
import AuthGuard from '@/components/AuthGuard'
import ImpactPanel from '@/components/ImpactPanel'
import SearchBar from '@/components/SearchBar'
import { fetchGraph } from '@/lib/api'
import { filterGraph } from '@/lib/graphFilter'
import { supabase } from '@/lib/supabase'
import { clearGithubToken } from '@/lib/githubToken'

const DependencyGraph = dynamic(
  () => import('@/components/DependencyGraph'),
  { ssr: false }
)

function NetworkLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 22 22" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="11" cy="3" r="2.5" fill="#fca311" />
      <circle cx="2.5" cy="17" r="2.5" fill="#fca311" />
      <circle cx="19.5" cy="17" r="2.5" fill="#fca311" />
      <line x1="11" y1="5.5" x2="3.8" y2="14.8" stroke="#fca311" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="11" y1="5.5" x2="18.2" y2="14.8" stroke="#fca311" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="5" y1="17" x2="17" y2="17" stroke="#fca311" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

// service_count/endpoint_count come from GET /graph regardless of whether any
// consumer_edges exist, so "never tracked" (both 0) can be told apart from
// "tracked but zero cross-service callers" (e.g. a single-service monolith --
// analyze.py's self-call exclusion means it can never have edges to itself).
function emptyStateMessage(repoId, serviceCount, endpointCount) {
  if (!repoId) return 'No repo selected — go to /repos and track one.'
  if (serviceCount > 0) {
    const serviceLabel = serviceCount === 1 ? 'service' : 'services'
    const endpointLabel = endpointCount === 1 ? 'endpoint' : 'endpoints'
    return `${repoId} has ${serviceCount} tracked ${serviceLabel} and ${endpointCount} ` +
      `tracked ${endpointLabel}, but no other tracked service calls them — this tool tracks ` +
      `cross-service consumers, not a single service's own routes.`
  }
  return 'This repo has no tracked services yet.'
}

function EmptyState({ repoId, serviceCount, endpointCount }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 select-none">
      <NetworkLogo />
      <div className="text-center max-w-md px-4">
        <p className="text-alabaster-300 text-sm font-mono mb-1">No graph loaded</p>
        <p className="text-alabaster-200 text-xs">
          {emptyStateMessage(repoId, serviceCount, endpointCount)}
        </p>
      </div>
    </div>
  )
}

export default function GraphPageInner() {
  const searchParams = useSearchParams()
  const repoId = searchParams.get('repo')

  const [nodes, setNodes] = useState([])
  const [edges, setEdges] = useState([])
  const [serviceCount, setServiceCount] = useState(0)
  const [endpointCount, setEndpointCount] = useState(0)
  const [graphLoading, setGraphLoading] = useState(false)
  const [graphError, setGraphError] = useState(null)
  const [selectedEndpoint, setSelectedEndpoint] = useState(null)
  const [search, setSearch] = useState('')

  useEffect(() => {
    setSelectedEndpoint(null)
    setSearch('')
    setGraphError(null)

    if (!repoId) {
      setNodes([])
      setEdges([])
      setServiceCount(0)
      setEndpointCount(0)
      setGraphLoading(false)
      return
    }

    let cancelled = false

    async function loadGraph() {
      setGraphLoading(true)
      try {
        const graphData = await fetchGraph(repoId)
        if (cancelled) return
        setNodes(graphData.nodes)
        setEdges(graphData.edges)
        setServiceCount(graphData.service_count ?? 0)
        setEndpointCount(graphData.endpoint_count ?? 0)
      } catch (err) {
        if (!cancelled) setGraphError(err.message)
      } finally {
        if (!cancelled) setGraphLoading(false)
      }
    }

    loadGraph()

    return () => {
      cancelled = true
    }
  }, [repoId])

  function handleNodeClick(event, node) {
    if (node.data.node_type !== 'endpoint') return
    const endpointId = parseInt(node.id.replace('ep:', ''), 10)
    setSelectedEndpoint({
      id: endpointId,
      functionName: node.data.function_name,
      method: node.data.method,
      path: node.data.path,
    })
  }

  async function handleLogout() {
    await supabase.auth.signOut()
    clearGithubToken()
    window.location.href = '/login'
  }

  const { visibleNodes, visibleEdges } = filterGraph(nodes, edges, search)

  return (
    <AuthGuard>
      <div className="flex flex-col h-screen bg-black overflow-hidden">

        {/* Header */}
        <header className="flex items-center gap-3 h-14 px-4 bg-prussian border-b border-prussian-600 shrink-0 z-10">
          <div className="flex items-center gap-2 shrink-0">
            <NetworkLogo />
            <span className="font-mono font-bold text-white text-sm tracking-tight hidden sm:block">
              EndpointGraph
            </span>
          </div>

          <div className="w-px h-6 bg-prussian-600 shrink-0" />

          <div className="flex-1 min-w-0">
            {repoId && (
              <span className="text-alabaster-300 text-sm font-mono truncate">{repoId}</span>
            )}
          </div>

          {nodes.length > 0 && (
            <>
              <div className="w-px h-6 bg-prussian-600 shrink-0" />
              <div className="w-52 shrink-0">
                <SearchBar value={search} onChange={setSearch} />
              </div>
            </>
          )}

          <div className="w-px h-6 bg-prussian-600 shrink-0" />

          <button
            onClick={handleLogout}
            className="text-alabaster-300 hover:text-alabaster text-xs font-mono shrink-0 transition-colors"
          >
            logout
          </button>
        </header>

        {/* Graph area */}
        <main className="flex-1 relative overflow-hidden">
          {graphLoading && (
            <div className="absolute inset-0 flex items-center justify-center z-10 bg-black bg-opacity-60">
              <div className="flex items-center gap-2 bg-prussian border border-prussian-600 px-5 py-3 rounded-lg">
                <span className="w-1.5 h-1.5 rounded-full bg-orange animate-pulse" />
                <span className="text-alabaster-300 text-sm font-mono">Loading graph…</span>
              </div>
            </div>
          )}

          {graphError && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 bg-prussian border border-red-800 text-red-400 text-xs font-mono px-4 py-2.5 rounded-lg max-w-sm text-center">
              {graphError}
            </div>
          )}

          {!graphLoading && nodes.length === 0 && (
            <EmptyState repoId={repoId} serviceCount={serviceCount} endpointCount={endpointCount} />
          )}

          {nodes.length > 0 && (
            <DependencyGraph
              nodes={visibleNodes}
              edges={visibleEdges}
              onNodeClick={handleNodeClick}
            />
          )}

          {selectedEndpoint && (
            <ImpactPanel
              endpointId={selectedEndpoint.id}
              functionName={selectedEndpoint.functionName}
              method={selectedEndpoint.method}
              path={selectedEndpoint.path}
              onClose={() => setSelectedEndpoint(null)}
            />
          )}
        </main>
      </div>
    </AuthGuard>
  )
}
