import { useQuery } from '@tanstack/react-query'
import { Info } from 'lucide-react'
import { useEffect, useId, useRef, useState, useSyncExternalStore, type CSSProperties, type MouseEvent } from 'react'
import { get } from '../lib/api'
import type { components } from '../lib/api-types'
import { useSession } from '../lib/queries'

type Methodology = components['schemas']['RiskMethodologyOut']

const useMethodology = (role: string | undefined) =>
  useQuery({ queryKey: ['risk-methodology', role], queryFn: () => get<Methodology>(`/risk-methodology?role=${role}`), enabled: !!role, staleTime: Infinity })

/** Одно окно P/S на весь интерфейс: какой значок активен и закреплено ли окно, хранится здесь, а не в каждом экземпляре.
 *  Новое наведение заменяет активный значок в том же рендере — два окна одновременно не показываются; отложенное закрытие одно на всех. */
type Active = { id: string; pinned: boolean } | null
const PS_GRACE_MS = 150  // только чтобы довести курсор от значка до окна
let active: Active = null
let closeTimer: number | undefined
const subs = new Set<() => void>()
function setActive(a: Active) {
  window.clearTimeout(closeTimer)
  closeTimer = undefined
  if (a?.id === active?.id && a?.pinned === active?.pinned) return
  active = a
  subs.forEach((f) => f())
}
const closeIfActive = (id: string) => { if (active?.id === id) setActive(null) }
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f) } }
const snapshot = () => active

/** Значок «i» рядом с P или S. Наведение и фокус — короткая подсказка; клик или касание — окно со шкалой и порогами.
 *  Закреплённое окно не сменяется наведением на другой значок; клик по другому значку переносит окно на него.
 *  Escape закрывает и возвращает фокус. Шкалы и пороги приходят с сервера (YAML-конфигурации). */
export function PsInfo({ what, sessionId }: { what: 'p' | 's'; sessionId: string }) {
  const role = useSession(sessionId).data?.role
  const m = useMethodology(role)
  const id = useId()
  const cur = useSyncExternalStore(subscribe, snapshot)
  const pinned = cur?.id === id && cur.pinned
  const hover = cur?.id === id && !cur.pinned
  const [pos, setPos] = useState<CSSProperties>({})
  const box = useRef<HTMLSpanElement>(null)
  const btn = useRef<HTMLButtonElement>(null)
  const pop = useRef<HTMLSpanElement>(null)
  useEffect(() => () => closeIfActive(id), [id])
  // Окно фиксируется у значка и не выходит за экран: панели с overflow: hidden его не обрезают.
  const place = (width: number) => {
    const r = btn.current?.getBoundingClientRect()
    if (!r) return
    const left = Math.max(16, Math.min(r.left - 8, window.innerWidth - width - 16))
    const above = r.top > window.innerHeight * 0.55
    setPos(above ? { left, bottom: window.innerHeight - r.top + 6, width, maxHeight: r.top - 22 } : { left, top: r.bottom + 6, width, maxHeight: window.innerHeight - r.bottom - 22 })
  }
  const show = () => { if (!active?.pinned) { place(256); setActive({ id, pinned: false }) } }
  // Уход в пустое место закрывает сразу; короткая задержка — только если курсор ушёл к самому окну (по пути к нему).
  const leave = (e: MouseEvent) => {
    if (active?.id !== id || active.pinned) return
    const p = pop.current?.getBoundingClientRect()
    const near = p && Math.max(p.left - e.clientX, e.clientX - p.right, 0) <= 8 && Math.max(p.top - e.clientY, e.clientY - p.bottom, 0) <= 24
    if (!near) { setActive(null); return }
    window.clearTimeout(closeTimer)
    closeTimer = window.setTimeout(() => { if (active?.id === id && !active.pinned) setActive(null) }, PS_GRACE_MS)
  }
  const open = hover || pinned
  useEffect(() => {
    if (!open) return
    const onScroll = (e: Event) => {
      if (box.current?.contains(e.target as Node)) return  // прокрутка внутри окна
      const r = btn.current?.getBoundingClientRect()
      if (!r || r.bottom < 0 || r.top > window.innerHeight) closeIfActive(id); else place(pinned ? 320 : 256)  // окно следует за значком
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { closeIfActive(id); btn.current?.focus() } }
    const onDown = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) closeIfActive(id) }
    window.addEventListener('scroll', onScroll, true)
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => { window.removeEventListener('scroll', onScroll, true); document.removeEventListener('keydown', onKey); document.removeEventListener('pointerdown', onDown) }
  }, [open, pinned, id])
  const d = m.data
  const title = what === 'p' ? 'Что означает P' : 'Что означает S'
  const short = d ? d.rules[what === 'p' ? 0 : 1] : 'Загружаем пояснение…'
  const scale = d ? (what === 'p' ? d.probability : d.severity) : null
  return (
    <span ref={box} className="relative inline-flex align-middle" onMouseEnter={() => { if (active?.id === id) window.clearTimeout(closeTimer) }} onMouseLeave={leave}>
      <button
        ref={btn} type="button" className="ps-info" aria-label={title} aria-expanded={pinned} aria-describedby={hover ? `${id}-tip` : undefined}
        onMouseEnter={show} onFocus={show}
        onBlur={(e) => { if (!pinned && !box.current?.contains(e.relatedTarget as Node)) closeIfActive(id) }}
        onClick={(e) => { e.stopPropagation(); place(320); setActive(pinned ? null : { id, pinned: true }) }}
      >
        <Info className="size-3.5" aria-hidden />
      </button>
      {hover && <span ref={pop} role="tooltip" id={`${id}-tip`} className="ps-pop body-s" style={pos}>{short}</span>}
      {pinned && (
        <span ref={pop} role="dialog" aria-label={title} className="ps-pop space-y-2 overflow-y-auto body-s" style={pos} onClick={(e) => e.stopPropagation()}>
          <b className="block">{what === 'p' ? 'P — вероятность' : 'S — тяжесть последствий'}{d ? ` (${d.measure})` : ''}</b>
          <span className="block">{short}</span>
          {scale && (
            <span className="block">
              {Object.entries(scale).map(([k, v]) => <span key={k} className="block"><span className="mono-m">{k}</span> — {v}</span>)}
            </span>
          )}
          {d && (
            <span className="block text-muted">
              Итог P × S: {d.levels.map((l) => `${l.label.toLowerCase()} ${l.min}–${l.max}`).join(', ')}.{' '}
              {d.rules.slice(2).join(' ')}
            </span>
          )}
          {m.isError && <span className="block text-risk-high">Пояснение не загрузилось.</span>}
        </span>
      )}
    </span>
  )
}
