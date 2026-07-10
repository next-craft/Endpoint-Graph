import { supabase } from './supabase'
import { storeGithubToken, getStoredGithubToken } from './githubToken'

async function getAuthHeaders() {
  const { data: { session } } = await supabase.auth.getSession()
  if (!session?.access_token)
    throw new Error('Session expired — please log in again')
  // session.provider_token isn't guaranteed to survive a background token
  // refresh, so fall back to the copy captured at login (see githubToken.js)
  // instead of failing every call after the first refresh.
  if (session.provider_token) storeGithubToken(session.provider_token)
  const githubToken = session.provider_token || getStoredGithubToken()
  if (!githubToken)
    throw new Error('Session expired — please log in again')
  return {
    'X-GitHub-Token': githubToken,
    'Authorization': `Bearer ${session.access_token}`,
  }
}

async function extractError(res) {
  const text = await res.text()
  try {
    const json = JSON.parse(text)
    if (typeof json.detail === 'string') return json.detail
    if (Array.isArray(json.detail)) return json.detail.map((e) => e.msg ?? String(e)).join(', ')
    return text
  } catch {
    return text
  }
}

export async function triggerAnalysis(repoUrl) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify({ repo_url: repoUrl }),
  })
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}

export async function fetchGraph(repoId) {
  const headers = await getAuthHeaders()
  const url = `${process.env.NEXT_PUBLIC_API_URL}/graph?repo_id=${encodeURIComponent(repoId)}`
  const res = await fetch(url, { headers })
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}

export async function fetchServices() {
  const headers = await getAuthHeaders()
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/services`, { headers })
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}

export async function fetchImpactAnalysis(endpointId) {
  const headers = await getAuthHeaders()
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/endpoints/${endpointId}/impact-analysis`,
    { headers }
  )
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}

export async function fetchUserRepos() {
  const headers = await getAuthHeaders()
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/repos`, { headers })
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}

export async function deleteService(serviceId) {
  const headers = await getAuthHeaders()
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/services/${serviceId}`, {
    method: 'DELETE',
    headers,
  })
  if (!res.ok) throw new Error(await extractError(res))
  return res.json()
}
