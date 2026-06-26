'use client'
import { supabase } from '@/lib/supabase'

export default function LoginPage() {
  const login = async () => {
    await supabase.auth.signInWithOAuth({
      provider: 'github',
      options: {
        scopes: 'repo',
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    })
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-950 text-white">
      <h1 className="text-4xl font-bold mb-3">EndpointGraph</h1>
      <p className="text-gray-400 mb-8">Discover who calls your APIs before you break them.</p>
      <button
        onClick={login}
        className="px-6 py-3 bg-white text-gray-950 font-semibold rounded-lg hover:bg-gray-200 transition-colors"
      >
        Login with GitHub
      </button>
    </div>
  )
}
