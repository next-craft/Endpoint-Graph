'use client'
import { useState, useEffect } from 'react'
import { fetchImpactAnalysis } from '@/lib/api'

function timeAgo(dateString) {
  const seconds = Math.floor((new Date() - new Date(dateString)) / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

const METHOD_COLORS = {
  GET:    '#7e99d5',
  POST:   '#fca311',
  PUT:    '#3e67bf',
  DELETE: '#ef4444',
  PATCH:  '#a78bfa',
}

export default function ImpactPanel({ endpointId, method, path, functionName, onClose }) {
  const [consumers, setConsumers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setConsumers([])
    fetchImpactAnalysis(endpointId)
      .then(setConsumers)
      .catch(() => setError('Failed to load consumers.'))
      .finally(() => setLoading(false))
  }, [endpointId])

  const maxCallCount = consumers.length > 0 ? Math.max(...consumers.map((c) => c.call_count)) : 1

  return (
    <div className="absolute right-0 top-0 h-full w-80 bg-prussian border-l border-prussian-600 flex flex-col z-10">
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-prussian-600">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-orange text-xs font-mono uppercase tracking-widest mb-1.5">
              Impact Analysis
            </p>
            {functionName && (
              <p className="font-mono text-xs text-alabaster-300 truncate">{functionName}</p>
            )}
            <div className="flex items-center gap-2 flex-wrap">
              {method && (
                <span
                  className="text-xs font-mono font-bold px-1.5 py-0.5 rounded"
                  style={{
                    color: METHOD_COLORS[method] ?? '#e5e5e5',
                    background: 'rgba(255,255,255,0.05)',
                    border: `1px solid ${METHOD_COLORS[method] ?? '#29447e'}`,
                  }}
                >
                  {method}
                </span>
              )}
              <span className="font-mono text-sm text-alabaster truncate">{path}</span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-alabaster-300 hover:text-alabaster transition-colors mt-0.5 shrink-0"
            aria-label="Close panel"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <line x1="1" y1="1" x2="13" y2="13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <line x1="13" y1="1" x2="1" y2="13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {!loading && !error && consumers.length > 0 && (
          <p className="text-alabaster-300 text-xs mt-3">
            <span className="text-orange font-mono font-bold">{consumers.length}</span>
            {' '}service{consumers.length !== 1 ? 's' : ''} will break if this endpoint changes
          </p>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center h-32">
            <p className="text-alabaster-300 text-xs font-mono">Loading…</p>
          </div>
        )}

        {error && (
          <div className="m-4 p-3 bg-prussian-300 border border-red-800 rounded">
            <p className="text-red-400 text-xs font-mono">{error}</p>
          </div>
        )}

        {!loading && !error && consumers.length === 0 && (
          <div className="flex flex-col items-center justify-center h-32 gap-2">
            <p className="text-alabaster-300 text-sm">No consumers found</p>
            <p className="text-alabaster-200 text-xs font-mono">This endpoint is safe to change</p>
          </div>
        )}

        {!loading && !error && consumers.length > 0 && (
          <ul className="p-4 space-y-3">
            {consumers.map((c, i) => {
              const barWidth = Math.round((c.call_count / maxCallCount) * 100)
              return (
                <li key={i} className="bg-prussian-300 border border-prussian-600 rounded-md p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-white font-mono truncate">
                      {c.caller_function_name ?? 'unknown'} in {c.caller_file_path ?? 'unknown file'} ({c.service_name})
                    </span>
                    <span className="text-xs font-mono text-alabaster-300 bg-prussian-400 px-1.5 py-0.5 rounded shrink-0 ml-2">
                      {c.source}
                    </span>
                  </div>

                  {/* Call count bar */}
                  <div className="mb-2">
                    <div className="h-1 bg-prussian-600 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-orange rounded-full transition-all"
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-xs text-alabaster-300 font-mono">
                    <span>{c.call_count.toLocaleString()} calls</span>
                    <span>{timeAgo(c.last_seen_at)}</span>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
