import { Suspense } from 'react'
import GraphPageInner from './GraphPageInner'

export default function GraphPage() {
  return (
    <Suspense fallback={null}>
      <GraphPageInner />
    </Suspense>
  )
}
