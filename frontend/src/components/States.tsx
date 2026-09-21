import { CircleAlert, Info, WifiOff } from 'lucide-react'
import type { ReactNode } from 'react'
import { errorText } from '../lib/api'
import { Button } from './ui'

export function Skeleton({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`} aria-hidden>
      {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton h-4" style={{ width: `${92 - ((i * 17) % 40)}%` }} />)}
    </div>
  )
}

export function Banner({ tone = 'info', children, action }: { tone?: 'info' | 'warn' | 'error'; children: ReactNode; action?: ReactNode }) {
  const cls = tone === 'error' ? 'risk-critical' : tone === 'warn' ? 'risk-medium' : 'risk-none'
  const Icon = tone === 'error' ? CircleAlert : Info
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`flex items-start gap-2 rounded-md px-3 py-2 text-small ${cls}`}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
      {action}
    </div>
  )
}

export function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <Banner tone="error" action={onRetry ? <Button onClick={onRetry}>Повторить</Button> : undefined}>
      {errorText(error)}
    </Banner>
  )
}

export function OfflineBanner() {
  return (
    <div role="alert" className="flex items-center gap-2 bg-risk-medium-soft px-4 py-1.5 text-small text-risk-medium">
      <WifiOff className="size-4" aria-hidden /> Нет соединения с интернетом. Введённый текст сохранён; отправка возобновится после восстановления связи.
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 px-4 py-10 text-center">
      <h3>{title}</h3>
      {children && <div className="text-small text-muted">{children}</div>}
      {action}
    </div>
  )
}
