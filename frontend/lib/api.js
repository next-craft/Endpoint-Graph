import { supabase } from './supabase'

async function getGitHubToken() {
  const { data: { session } } = await supabase.auth.getSession()
  return session?.provider_token
}

export async function triggerAnalysis(repoUrl) {
  const token = await getGitHubToken()
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-GitHub-Token': token,
    },
    body: JSON.stringify({ repo_url: repoUrl }),
  })
  return res.json()
}

export async function fetchGraph() {
  const token = await getGitHubToken()
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/graph`, {
    headers: { 'X-GitHub-Token': token },
  })
  return res.json()
}

export async function fetchServices() {
  const token = await getGitHubToken()
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/services`, {
    headers: { 'X-GitHub-Token': token },
  })
  return res.json()
}

export async function fetchImpactAnalysis(endpointId) {
  const token = await getGitHubToken()
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL}/endpoints/${endpointId}/impact-analysis`,
    { headers: { 'X-GitHub-Token': token } }
  )
  return res.json()
}
