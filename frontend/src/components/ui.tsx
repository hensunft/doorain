import { CircleDot, Loader2, OctagonAlert, ShieldAlert, TriangleAlert } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'
import type { Level } from '../lib/api'
import { LEVEL_RU } from '../lib/risk'

export function Spinner({ label }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-muted text-small">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label ?? <span className="sr-only">Загрузка</span>}
    </span>
  )
}

const LEVEL_ICON = { low: CircleDot, medium: TriangleAlert, high: OctagonAlert, critical: ShieldAlert } as const

/** Уровень риска дублируется текстом, значком и числом — цвет не единственный носитель смысла. */
export function RiskBadge({ level, score, compact = false }: { level: Level | null; score?: number | null; compact?: boolean }) {
  if (!level) return <span className="chip risk-none">не оценён</span>
  const Icon = LEVEL_ICON[level]
  return (
    <span className={`chip risk-${level} tnum`} style={{ borderColor: 'transparent' }} data-level={level}>
      <Icon className="size-3.5" aria-hidden />
      {!compact && LEVEL_RU[level]}
      {score != null && <span>{compact ? `${LEVEL_RU[level]} ` : ''}{score}</span>}
    </span>
  )
}

export function Field({ label, hint, children, id }: { label: string; hint?: string; children: ReactNode; id: string }) {
  return (
    <div>
      <label className="label" htmlFor={id}>{label}</label>
      {children}
      {hint && <p className="hint mt-1">{hint}</p>}
    </div>
  )
}

export function Button({ variant = 'default', className = '', ...p }: ComponentProps<'button'> & { variant?: 'default' | 'primary' | 'quiet' | 'danger' }) {
  const v = variant === 'primary' ? 'btn-primary' : variant === 'quiet' ? 'btn-quiet' : variant === 'danger' ? 'btn-danger' : ''
  return <button type="button" {...p} className={`btn ${v} ${className}`} />
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>
}
