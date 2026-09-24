import { CircleDot, HelpCircle, Loader2, OctagonAlert, ShieldAlert, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from 'react'
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

export function Field({ label, hint, children, id, info }: { label: string; hint?: string; children: ReactNode; id: string; info?: ReactNode }) {
  return (
    <div>
      <span className="flex items-center"><label className="label" htmlFor={id}>{label}</label>{info}</span>
      {children}
      {hint && <p className="hint mt-1">{hint}</p>}
    </div>
  )
}

const VARIANT = { secondary: '', primary: 'btn-primary', tertiary: 'btn-tertiary', danger: 'btn-danger', 'danger-solid': 'btn-danger-solid' } as const

/** Кнопка системы: первичная — одна на экран; danger-solid — только в диалоге подтверждения. loading — текст остаётся, ширина не меняется. */
export function Button({ variant = 'secondary', size, loading = false, className = '', disabled, ...p }: ComponentProps<'button'> & { variant?: keyof typeof VARIANT; size?: 'lg'; loading?: boolean }) {
  return <button type="button" {...p} disabled={disabled || loading} aria-busy={loading || undefined} className={`btn ${VARIANT[variant]} ${size === 'lg' ? 'btn-lg' : ''} ${className}`} />
}

/** Кнопка «?» и поповер по требованию: пояснения не занимают постоянного места и рендерятся только открытыми. */
export function HelpPopover({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: Event) => {
      if (e.type === 'keydown' ? (e as globalThis.KeyboardEvent).key === 'Escape' : !box.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', close)
    document.addEventListener('pointerdown', close)
    return () => { document.removeEventListener('keydown', close); document.removeEventListener('pointerdown', close) }
  }, [open])
  return (
    <div ref={box} className="relative">
      <button type="button" className="btn btn-icon btn-tertiary" aria-label={label} aria-expanded={open} onClick={() => setOpen(!open)}><HelpCircle className="size-4" aria-hidden /></button>
      {open && <div role="dialog" aria-label={label} className="zone absolute right-0 z-30 mt-1 w-80 border border-line shadow-[var(--shadow-hover)]">{children}</div>}
    </div>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>
}
