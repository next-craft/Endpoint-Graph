'use client'
import { useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { supabase } from '@/lib/supabase'

export default function AuthCallbackInner() {
  const router = useRouter()
  const searchParams = useSearchParams()

  useEffect(() => {
    async function handleCallback() {
      const code = searchParams.get('code')
      if (code) {
        await supabase.auth.exchangeCodeForSession(code)
      }
      router.replace('/graph')
    }
    handleCallback()
  }, [router, searchParams])

  return null
}
