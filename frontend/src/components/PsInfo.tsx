import { useQuery } from '@tanstack/react-query'
import { Info } from 'lucide-react'
import { useEffect, useId, useRef, useState, type CSSProperties } from 'react'
import { get } from '../lib/api'
import type { components } from '../lib/api-types'
import { useSession } from '../lib/queries'

type Methodology = components['schemas']['RiskMethodologyOut']

const useMethodology = (role: string | undefined) =>
  useQuery({ queryKey: ['risk-methodology', role], queryFn: () => get<Methodology>(`/risk-methodology?role=${role}`), enabled: !!role, staleTime: Infinity })

/** Значок «i» рядом с P или S. Наведение и фокус — короткая подсказка; клик или касание — окно со шкалой и порогами.
 *  Escape закрывает; курсор можно перевести в окно — оно не исчезает сразу. Шкалы и пороги приходят с сервера (YAML-конфигурации). */
export function PsInfo({ what, sessionId }: { what: 'p' | 's'; sessionId: string }) {
  const role = useSession(sessionId).data?.role
  const m = useMethodology(role)
  const [hover, setHover] = useState(false)
  const [pinned, setPinned] = useState(false)
  const [pos, setPos] = useState<CSSProperties>({})
  const timer = useRef<number | undefined>(undefined)
  const box = useRef<HTMLSpanElement>(null)
  const btn = useRef<HTMLButtonElement>(null)
  const id = useId()
  const keep = () => window.clearTimeout(timer.current)
  const leave = () => { keep(); timer.current = window.setTimeout(() => setHover(false), 250) }
  useEffect(() => () => window.clearTimeout(timer.current), [])
  // Окно фиксируется у значка и не выходит за экран: панели с overflow: hidden его не обрезают.
  const place = (width: number) => {
    const r = btn.current?.getBoundingClientRect()
    if (!r) return
    const left = Math.max(16, Math.min(r.left - 8, window.innerWidth - width - 16))
    const above = r.top > window.innerHeight * 0.55
    setPos(above ? { left, bottom: window.innerHeight - r.top + 6, width, maxHeight: r.top - 22 } : { left, top: r.bottom + 6, width, maxHeight: window.innerHeight - r.bottom - 22 })
  }
  useEffect(() => {
    if (!pinned && !hover) return
    const onScroll = (e: Event) => {
      if (box.current?.contains(e.target as Node)) return  // прокрутка внутри окна
      const r = btn.current?.getBoundingClientRect()
      if (!r || r.bottom < 0 || r.top > window.innerHeight) { setPinned(false); setHover(false) } else place(pinned ? 320 : 256)  // окно следует за значком
    }
    window.addEventListener('scroll', onScroll, true)
    return () => window.removeEventListener('scroll', onScroll, true)
  }, [pinned, hover])
  useEffect(() => {
    if (!pinned && !hover) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setPinned(false); setHover(false); btn.current?.focus() } }
    const onDown = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) { setPinned(false); setHover(false) } }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('pointerdown', onDown) }
  }, [pinned, hover])
  const d = m.data
  const title = what === 'p' ? 'Что означает P' : 'Что означает S'
  const short = d ? d.rules[what === 'p' ? 0 : 1] : 'Загружаем пояснение…'
  const scale = d ? (what === 'p' ? d.probability : d.severity) : null
  return (
    <span ref={box} className="relative inline-flex align-middle" onMouseEnter={keep} onMouseLeave={() => !pinned && leave()}>
      <button
        ref={btn} type="button" className="ps-info" aria-label={title} aria-expanded={pinned} aria-describedby={hover && !pinned ? `${id}-tip` : undefined}
        onMouseEnter={() => { keep(); place(256); setHover(true) }} onFocus={() => { place(256); setHover(true) }}
        onBlur={(e) => { if (!pinned && !box.current?.contains(e.relatedTarget as Node)) setHover(false) }}
        onClick={(e) => { e.stopPropagation(); place(320); setPinned(!pinned) }}
      >
        <Info className="size-3.5" aria-hidden />
      </button>
      {hover && !pinned && <span role="tooltip" id={`${id}-tip`} className="ps-pop body-s" style={pos}>{short}</span>}
      {pinned && (
        <span role="dialog" aria-label={title} className="ps-pop space-y-2 overflow-y-auto body-s" style={pos} onClick={(e) => e.stopPropagation()}>
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
