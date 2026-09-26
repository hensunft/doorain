import { BaseEdge, EdgeLabelRenderer, Handle, Position, useInternalNode, type Edge, type EdgeProps, type InternalNode, type Node, type NodeProps } from '@xyflow/react'
import { useEffect, useRef, type CSSProperties } from 'react'
import { Medallion } from '../../components/Medallion'
import type { GraphNode, Level } from '../../lib/api'
import { levelVar } from '../../lib/risk'
import { growth, normParts, short, swingPush, swingStep, type Swing } from './graphModel'

export interface PData extends Record<string, unknown> {
  kind: GraphNode['kind']
  label: string
  level: Level | null
  past: Level | null
  count: number
  weight: number
  num?: number
  counters?: string
  role?: string
  dim: boolean
  active: boolean
  title: string
}

/** Цвета узла из токенов уровня: заливка (ромб), текст на заливке, обводка (для снятого риска — след прежнего цвета),
 *  полупрозрачная подложка и читаемый оттенок уровня для номера вопроса. */
function paint(level: Level | null, past: Level | null): CSSProperties {
  const tok = level === 'medium' ? 'mid' : level
  return {
    ['--fill' as string]: level ? levelVar(level) : 'var(--risk-none-tint)',
    ['--ink-on' as string]: level ? (level === 'medium' ? 'var(--on-risk-mid)' : 'var(--on-risk)') : 'var(--ink)',
    ['--edge' as string]: level ? levelVar(level) : past ? levelVar(past) : 'var(--line-strong)',
    ['--edge-ink' as string]: level ? `var(--risk-${tok}-ink)` : 'var(--ink-2)',
    ['--tint' as string]: level ? `var(--risk-${tok}-tint)` : 'var(--risk-none-tint)',
  }
}

const hidden = { opacity: 0, pointerEvents: 'none' as const, border: 0, background: 'transparent', width: 1, height: 1, minWidth: 0, minHeight: 0 }

function Shell({ data, children }: { data: PData; children: React.ReactNode }) {
  return (
    <div className="gn" data-dim={data.dim} data-active={data.active} title={data.title} style={paint(data.level, data.past)}>
      <Handle type="target" position={Position.Top} style={hidden} />
      {children}
      <Handle type="source" position={Position.Bottom} style={hidden} />
    </div>
  )
}

/** Ромб-счётчик на краю узла: риск — не самостоятельный узел, а бейдж с числом активных рисков. */
function Diamond({ data, style }: { data: PData; style?: CSSProperties }) {
  if (!data.count) return null
  return <span className="gn-diamond" style={style} aria-hidden><span>{data.count}</span></span>
}

/** Весы качаются, когда узел двигают: каждый сдвиг по x толкает маятник чаш, затухание считается в requestAnimationFrame,
 *  углы пишутся в CSS-переменные --pan/--beam элемента (без перерисовки React). При prefers-reduced-motion весы неподвижны. */
function useSwing(x: number) {
  const ref = useRef<HTMLDivElement>(null)
  const st = useRef({ x, raf: 0, t: 0, s: { pan: 0, panV: 0, beam: 0, beamV: 0 } as Swing })
  useEffect(() => {
    const m = st.current
    const dx = x - m.x
    m.x = x
    if (!dx || matchMedia('(prefers-reduced-motion: reduce)').matches) return
    swingPush(m.s, dx)
    if (m.raf) return
    m.t = performance.now()
    const tick = (now: number) => {
      const going = swingStep(m.s, Math.min(0.033, (now - m.t) / 1000))
      m.t = now
      if (!going) m.s = { pan: 0, panV: 0, beam: 0, beamV: 0 }
      ref.current?.style.setProperty('--pan', `${m.s.pan.toFixed(2)}deg`)
      ref.current?.style.setProperty('--beam', `${m.s.beam.toFixed(2)}deg`)
      m.raf = going ? requestAnimationFrame(tick) : 0
    }
    m.raf = requestAnimationFrame(tick)
  }, [x])
  useEffect(() => () => cancelAnimationFrame(st.current.raf), [])
  return ref
}

/** «Вы» — якорь портрета: медальон с весами (при перетаскивании чаши качаются), под ним роль и тема сессии. */
function CenterNode({ data, positionAbsoluteX }: NodeProps<Node<PData>>) {
  const swing = useSwing(positionAbsoluteX)
  return (
    <Shell data={data}>
      <div className="gn-center" ref={swing}><Medallion size={120} /></div>
      <span className="serif mt-1.5 text-[17px] font-semibold leading-none">Вы</span>
      <span className="overline mt-1">{data.role}</span>
      <span className="caption mt-0.5 max-w-[180px] truncate">{short(data.label, 40)}</span>
    </Shell>
  )
}

function TopicNode({ data }: NodeProps<Node<PData>>) {
  const k = growth(data.weight)
  return (
    <Shell data={data}>
      <div className="gn-topic" style={{ transform: `scale(${k})` }}>
        <p className="body-m font-semibold leading-tight" style={{ color: 'inherit' }}>{short(data.label, 34)}</p>
        {data.counters && <p className="leading-tight" style={{ color: 'inherit', fontSize: 10, opacity: 0.9 }}>{data.counters}</p>}
        <Diamond data={data} style={{ right: -8, top: '50%', marginTop: -10 }} />
      </div>
    </Shell>
  )
}

function QuestionNode({ data }: NodeProps<Node<PData>>) {
  return (
    <Shell data={data}>
      <div className="gn-question">
        <span className="gn-num">{data.num}</span>
        <span className="body-s leading-tight">{short(data.label, 60)}</span>
        <Diamond data={data} style={{ right: -9, top: -9 }} />
      </div>
    </Shell>
  )
}

function NormNode({ data }: NodeProps<Node<PData>>) {
  const { act, loc } = normParts(data.label)
  const k = growth(data.weight)
  const w = Math.round(46 * k), h = Math.round(40 * k)
  return (
    <Shell data={data}>
      <div className="gn-norm relative" data-risk={!!data.level} style={{ width: w, height: h }}>
        <svg width={w} height={h} viewBox="0 0 46 40" aria-hidden>
          <polygon points="12,2 34,2 44,20 34,38 12,38 2,20" />
        </svg>
        <span className="mono-m absolute inset-0 flex items-center justify-center font-medium" style={{ color: 'var(--chip-norm-ink)' }}>{act}</span>
      </div>
      {loc && <span className="gn-cap">{short(loc, 16)}</span>}
    </Shell>
  )
}

function RiskNode({ data }: NodeProps<Node<PData>>) {
  return (
    <Shell data={data}>
      <div className="gn-risk" />
      <span className="gn-cap max-w-[160px] truncate">{data.label}</span>
    </Shell>
  )
}

export const nodeTypes = { center: CenterNode, topic: TopicNode, question: QuestionNode, norm: NormNode, risk: RiskNode }

export interface EData extends Record<string, unknown> { arrow: boolean; label: string; hot: boolean }

/** Центр узла и точка на его границе в сторону другого узла. «Вы» — круг медальона (подписи под ним не задеваются),
 *  капсула темы — с учётом масштаба, остальные — рамка узла. */
function centre(n: InternalNode): { x: number; y: number } {
  const p = n.internals.positionAbsolute, w = n.measured.width ?? 0, h = n.measured.height ?? 0
  return { x: p.x + w / 2, y: n.type === 'center' ? p.y + 60 : p.y + h / 2 }
}
function rim(n: InternalNode, toward: { x: number; y: number }): { x: number; y: number } {
  const c = centre(n), dx = toward.x - c.x, dy = toward.y - c.y, len = Math.hypot(dx, dy) || 1
  if (n.type === 'center') { // круг медальона; вниз — от нижнего края узла, чтобы линия не шла по подписям «Вы» и роли
    const o = { x: c.x + (dx / len) * 64, y: c.y + (dy / len) * 64 }
    const bottom = n.internals.positionAbsolute.y + (n.measured.height ?? 0)
    const xb = dy > 0 ? c.x + (dx / dy) * (bottom - c.y) : Infinity
    return Math.abs(xb - c.x) < (n.measured.width ?? 0) / 2 ? { x: xb, y: bottom } : o
  }
  const k = n.type === 'topic' ? growth(Number((n.data as PData).weight) || 1) : 1
  const hw = ((n.measured.width ?? 0) * k) / 2 + 3, hh = ((n.measured.height ?? 0) * k) / 2 + 3
  const t = Math.min(hw / Math.max(Math.abs(dx), 1e-6), hh / Math.max(Math.abs(dy), 1e-6), 1)
  return { x: c.x + dx * t, y: c.y + dy * t }
}

/** Связь «от узла к узлу»: прямая между границами (не от скрытых ручек сверху и снизу, поэтому не режет соседние узлы),
 *  стрелка — куда ведёт связь (от «Вы» наружу), при наведении — подпись «что → куда» посередине. */
function FloatEdge({ id, source, target, style, data }: EdgeProps<Edge<EData>>) {
  const a = useInternalNode(source), b = useInternalNode(target)
  if (!a || !b) return null
  const s = rim(a, centre(b)), t = rim(b, centre(a))
  const len = Math.hypot(t.x - s.x, t.y - s.y) || 1, ux = (t.x - s.x) / len, uy = (t.y - s.y) / len
  const head = data?.arrow ? 7 : 0 // линия заканчивается у основания стрелки, остриё — на границе узла
  const stroke = style?.stroke ?? 'var(--line-strong)'
  return (
    <>
      <BaseEdge id={id} path={`M ${s.x},${s.y} L ${t.x - ux * head},${t.y - uy * head}`} style={style} interactionWidth={16} />
      {data?.arrow && <path d={`M ${t.x},${t.y} L ${t.x - ux * 8 - uy * 3.6},${t.y - uy * 8 + ux * 3.6} L ${t.x - ux * 8 + uy * 3.6},${t.y - uy * 8 - ux * 3.6} Z`} style={{ fill: stroke, opacity: style?.opacity }} />}
      {data?.hot && data.label && (
        <EdgeLabelRenderer>
          <div className="edge-label" style={{ transform: `translate(-50%, -50%) translate(${(s.x + t.x) / 2}px, ${(s.y + t.y) / 2}px)` }}>{data.label}</div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

export const edgeTypes = { float: FloatEdge }
