'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { triggerAnalysis, fetchUserRepos, deleteService } from '@/lib/api'

// repos: array of repo objects from GET /repos
// onUpdate: (newRepos: array) => void — replaces the repos state in the parent
export default function RepoList({ repos, onUpdate }) {
  const router = useRouter()
  const [rowLoading, setRowLoading] = useState({})
  const [rowError, setRowError] = useState({})

  const setLoading = (fullName, action) =>
    setRowLoading((prev) => ({ ...prev, [fullName]: action }))
  const clearLoading = (fullName) =>
    setRowLoading((prev) => ({ ...prev, [fullName]: null }))
  const setError = (fullName, msg) =>
    setRowError((prev) => ({ ...prev, [fullName]: msg || null }))

  async function handleTrack(repo) {
    setLoading(repo.full_name, 'track')
    setError(repo.full_name, null)
    try {
      await triggerAnalysis(`https://github.com/${repo.full_name}`)
      router.push(`/graph?repo=${repo.full_name}`)
    } catch (err) {
      setError(repo.full_name, err.message)
      clearLoading(repo.full_name)
    }
  }

  async function handleReanalyze(repo) {
    setLoading(repo.full_name, 'reanalyze')
    setError(repo.full_name, null)
    try {
      await triggerAnalysis(`https://github.com/${repo.full_name}`)
      const updated = await fetchUserRepos()
      onUpdate(updated)
    } catch (err) {
      setError(repo.full_name, err.message)
    } finally {
      clearLoading(repo.full_name)
    }
  }

  async function handleUntrack(repo) {
    setLoading(repo.full_name, 'untrack')
    setError(repo.full_name, null)
    try {
      await deleteService(repo.service_id)
      // Reflect the untrack immediately once the delete has committed — don't
      // wait on the refetch below, so a slow or failing refetch can't leave
      // the row looking still-tracked and require a second click to notice.
      onUpdate(repos.map((r) =>
        r.full_name === repo.full_name
          ? { ...r, tracked: false, service_id: null, last_analyzed_at: null }
          : r
      ))
      try {
        const updated = await fetchUserRepos()
        onUpdate(updated)
      } catch {
        // The optimistic update above already reflects the successful
        // delete — a failed refetch doesn't need to surface as an error.
      }
    } catch (err) {
      setError(repo.full_name, err.message)
    } finally {
      clearLoading(repo.full_name)
    }
  }

  if (repos.length === 0) {
    return <p className="text-alabaster-300 text-sm font-mono">No repositories found.</p>
  }

  return (
    <ul className="space-y-3">
      {repos.map((repo) => {
        const activeAction = rowLoading[repo.full_name]
        const err = rowError[repo.full_name]
        const isLoading = Boolean(activeAction)

        return (
          <li key={repo.full_name} className="bg-prussian border border-prussian-600 rounded-lg p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono font-bold text-white truncate">{repo.name}</span>
                  <span
                    className={
                      repo.private
                        ? 'text-xs font-mono px-2 py-0.5 rounded-full bg-orange-100 text-orange'
                        : 'text-xs font-mono px-2 py-0.5 rounded-full bg-prussian-400 text-alabaster-300'
                    }
                  >
                    {repo.private ? 'Private' : 'Public'}
                  </span>
                </div>
                <p className="text-alabaster-300 text-xs font-mono mt-0.5">{repo.full_name}</p>
                <p className="text-alabaster-400 text-xs font-mono mt-1">
                  Last analyzed:{' '}
                  {repo.last_analyzed_at
                    ? new Date(repo.last_analyzed_at).toLocaleString()
                    : 'Never'}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {repo.tracked ? (
                  <>
                    <button
                      disabled={isLoading}
                      onClick={() => handleReanalyze(repo)}
                      className="text-sm font-mono px-3 py-1.5 rounded border border-prussian-600 text-alabaster-300 hover:text-alabaster disabled:opacity-50 transition-colors"
                    >
                      {activeAction === 'reanalyze' ? 'Analyzing…' : 'Re-analyze'}
                    </button>
                    <button
                      disabled={isLoading}
                      onClick={() => handleUntrack(repo)}
                      className="text-sm font-mono px-3 py-1.5 rounded border border-red-800 text-red-400 hover:bg-red-950 disabled:opacity-50 transition-colors"
                    >
                      {activeAction === 'untrack' ? 'Untracking…' : 'Untrack'}
                    </button>
                  </>
                ) : (
                  <button
                    disabled={isLoading}
                    onClick={() => handleTrack(repo)}
                    className="text-sm font-mono font-bold px-3 py-1.5 rounded bg-orange text-black hover:bg-orange-600 disabled:opacity-50 transition-colors"
                  >
                    {activeAction === 'track' ? 'Tracking…' : 'Track'}
                  </button>
                )}
              </div>
            </div>
            {err && (
              <p className="text-red-400 text-xs font-mono mt-1">{err}</p>
            )}
          </li>
        )
      })}
    </ul>
  )
}
