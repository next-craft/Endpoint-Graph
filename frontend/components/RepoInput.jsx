'use client'
import { useState } from 'react'
import { triggerAnalysis } from '@/lib/api'

export default function RepoInput({ onAnalysisComplete }) {
  const [repoUrl, setRepoUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleAnalyze() {
    setLoading(true)
    setError(null)
    try {
      await triggerAnalysis(repoUrl)
      onAnalysisComplete()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <input
        type="text"
        value={repoUrl}
        onChange={(e) => setRepoUrl(e.target.value)}
        placeholder="github.com/owner/repo"
      />
      <button onClick={handleAnalyze} disabled={loading}>
        Analyze
      </button>
      {error && <p>{error}</p>}
    </div>
  )
}
