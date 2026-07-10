'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import AuthGuard from '@/components/AuthGuard'
import RepoList from '@/components/RepoList'
import { fetchUserRepos } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import { clearGithubToken } from '@/lib/githubToken'

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

export default function ReposPage() {
  const [loading, setLoading] = useState(true)
  const [repos, setRepos] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    async function load() {
      try {
        const data = await fetchUserRepos()
        setRepos(data)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  async function handleLogout() {
    await supabase.auth.signOut()
    clearGithubToken()
    window.location.href = '/login'
  }

  const trackedRepo = repos.find((r) => r.tracked)

  return (
    <AuthGuard>
      <div className="min-h-screen bg-black">
        <header className="flex items-center gap-3 h-14 px-4 bg-prussian border-b border-prussian-600">
          <div className="flex items-center gap-2 shrink-0">
            <NetworkLogo />
            <span className="font-mono font-bold text-white text-sm tracking-tight hidden sm:block">
              EndpointGraph
            </span>
          </div>

          <div className="flex-1 min-w-0" />

          {trackedRepo && (
            <>
              <Link
                href={`/graph?repo=${trackedRepo.full_name}`}
                className="text-alabaster-300 hover:text-alabaster text-xs font-mono shrink-0 transition-colors"
              >
                Graph →
              </Link>
              <div className="w-px h-6 bg-prussian-600 shrink-0" />
            </>
          )}

          <button
            onClick={handleLogout}
            className="text-alabaster-300 hover:text-alabaster text-xs font-mono shrink-0 transition-colors"
          >
            logout
          </button>
        </header>

        <main className="p-8">
          <h1 className="text-2xl font-bold text-white mb-6 tracking-tight">Your Repositories</h1>
          {loading && (
            <div data-testid="loading-spinner" className="flex justify-center mt-16">
              <div className="w-8 h-8 rounded-full border-t-2 border-orange animate-spin" />
            </div>
          )}
          {error && (
            <p className="text-red-400 text-xs font-mono mb-4">{error}</p>
          )}
          {!loading && <RepoList repos={repos} onUpdate={setRepos} />}
        </main>
      </div>
    </AuthGuard>
  )
}
