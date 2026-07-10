// Supabase only guarantees session.provider_token is populated once, right
// after the initial OAuth callback — it drops out of the session object on
// later background access-token refreshes. Capture it once and keep our own
// copy so API calls don't depend on it surviving a refresh.
const STORAGE_KEY = 'eg_github_token'

export function storeGithubToken(token) {
  if (typeof window === 'undefined' || !token) return
  window.sessionStorage.setItem(STORAGE_KEY, token)
}

export function getStoredGithubToken() {
  if (typeof window === 'undefined') return null
  return window.sessionStorage.getItem(STORAGE_KEY)
}

export function clearGithubToken() {
  if (typeof window === 'undefined') return
  window.sessionStorage.removeItem(STORAGE_KEY)
}
