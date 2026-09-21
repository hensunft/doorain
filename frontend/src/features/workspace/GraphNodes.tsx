import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { CSSProperties } from 'react'
import type { GraphNode, Level } from '../../lib/api'
import { levelVar } from '../../lib/risk'
import { growth, normParts, short } from './graphModel'

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

/** Цвета узла из токенов уровня: заливка, текст на заливке, обводка (для снятого риска — след прежнего цвета). */
function paint(level: Level | null, past: Level | null): CSSProperties {
  return {
    ['--fill' as string]: level ? levelVar(level) : 'var(--risk-none-tint)',
    ['--ink-on' as string]: level ? (level === 'medium' ? 'var(--on-risk-mid)' : 'var(--on-risk)') : 'var(--ink)',
    ['--edge' as string]: level ? levelVar(level) : past ? levelVar(past) : 'var(--line-strong)',
    ['--tint' as string]: level ? `var(--risk-${level === 'medium' ? 'mid' : level}-tint)` : 'var(--surface-3)',
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

function CenterNode({ data }: NodeProps<Node<PData>>) {
  return (
    <Shell data={data}>
      <div className="gn-center">
        <span className="display-s" style={{ color: 'inherit', fontSize: 22, lineHeight: 1 }}>ВЫ</span>
        <span className="caption" style={{ color: 'inherit', opacity: 0.85, fontSize: 10 }}>{data.role}</span>
      </div>
      <span className="caption mt-2 max-w-[180px] truncate">{short(data.label, 40)}</span>
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
      <div className="gn-norm relative" data-level={!!data.level} style={{ width: w, height: h }}>
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
