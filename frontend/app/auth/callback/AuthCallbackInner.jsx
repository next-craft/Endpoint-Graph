'use client'
import { useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { supabase } from '@/lib/supabase'
import { storeGithubToken } from '@/lib/githubToken'

export default function AuthCallbackInner() {
  const router = useRouter()
  const searchParams = useSearchParams()

  useEffect(() => {
    async function handleCallback() {
      const code = searchParams.get('code')
      if (code) {
        const { data } = await supabase.auth.exchangeCodeForSession(code)
        storeGithubToken(data?.session?.provider_token)
      }
      router.replace('/graph')
    }
    handleCallback()
  }, [router, searchParams])

  return null
}
