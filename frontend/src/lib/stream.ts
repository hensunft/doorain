/** Состояние потока run и SSE-подписка. Текст — по завершённым блокам; answer_completed заменяет предварительный буфер. */
import { useEffect, useReducer, useRef } from 'react'
import type { Block, RunSnapshot } from './api'
import { get } from './api'

export interface StreamState {
  blocks: Block[]
  stage: string | null
  stageMessage: string | null
  final: 'validated' | 'refused' | 'cancelled' | 'failed' | null
  analysis: 'idle' | 'running' | 'completed' | 'failed'
  done: boolean
  connection: 'connecting' | 'open' | 'reconnecting' | 'closed'
  error: string | null
  warnings: string[]
  provisional: boolean
}

export const initialStream: StreamState = { blocks: [], stage: null, stageMessage: null, final: null, analysis: 'idle', done: false, connection: 'connecting', error: null, warnings: [], provisional: true }

export type StreamEvent =
  | { type: 'status'; data: { stage?: string; message?: string } }
  | { type: 'answer_delta' | 'answer_block_replaced'; data: { block: Block } }
  | { type: 'answer_completed'; data: { blocks: Block[]; answer_status: StreamState['final']; warnings?: string[] } }
  | { type: 'analysis_started' | 'portrait_updated' | 'risk_updated'; data: Record<string, unknown> }
  | { type: 'completed'; data: { answer_status?: StreamState['final']; analysis_status?: string } }
  | { type: 'failed'; data: { message?: string; blocks?: Block[] } }
  | { type: 'cancelled'; data: { blocks?: Block[]; phase?: string } }
  | { type: '__connection'; data: { state: StreamState['connection'] } }
  | { type: '__snapshot'; data: RunSnapshot }

export function reduceStream(s: StreamState, ev: StreamEvent): StreamState {
  switch (ev.type) {
    case 'status':
      if (ev.data.stage === 'restarted') return { ...s, blocks: [], stage: ev.data.stage, stageMessage: ev.data.message ?? null }
      if (ev.data.stage === 'analysis_failed') return { ...s, analysis: 'failed', stage: ev.data.stage, stageMessage: ev.data.message ?? null }
      return { ...s, stage: ev.data.stage ?? s.stage, stageMessage: ev.data.message ?? s.stageMessage }
    case 'answer_delta':
    case 'answer_block_replaced': {
      const b = ev.data.block
      const i = s.blocks.findIndex((x) => x.id === b.id)
      if (b.removed) return { ...s, blocks: s.blocks.filter((x) => x.id !== b.id) }
      if (i >= 0) {
        const cur = s.blocks[i]
        if (cur && cur.version > b.version) return s
        const next = s.blocks.slice()
        next[i] = b
        return { ...s, blocks: next }
      }
      return { ...s, blocks: [...s.blocks, b] }
    }
    case 'answer_completed':
      // канонический ответ заменяет предварительный клиентский буфер целиком
      return { ...s, blocks: ev.data.blocks, final: ev.data.answer_status ?? s.final, warnings: ev.data.warnings ?? s.warnings, provisional: false }
    case 'analysis_started':
      return { ...s, analysis: 'running' }
    case 'portrait_updated':
    case 'risk_updated':
      return s
    case 'completed':
      return { ...s, done: true, provisional: false, final: ev.data.answer_status ?? s.final, analysis: ev.data.analysis_status === 'failed' ? 'failed' : ev.data.analysis_status === 'completed' ? 'completed' : s.analysis === 'running' ? 'completed' : s.analysis }
    case 'failed':
      return { ...s, done: true, provisional: false, final: 'failed', blocks: ev.data.blocks ?? s.blocks, error: ev.data.message ?? 'Ошибка обработки' }
    case 'cancelled':
      return { ...s, done: true, provisional: false, final: ev.data.phase === 'analysis' ? s.final : 'cancelled', analysis: ev.data.phase === 'analysis' ? 'failed' : s.analysis, blocks: ev.data.blocks ?? s.blocks }
    case '__connection':
      return { ...s, connection: ev.data.state }
    case '__snapshot': {
      const sn = ev.data
      return { ...s, blocks: sn.blocks.length ? sn.blocks : s.blocks, final: (['validated', 'refused', 'cancelled', 'failed'] as const).find((x) => x === sn.answer_status) ?? s.final, analysis: sn.analysis_status === 'completed' ? 'completed' : sn.analysis_status === 'failed' ? 'failed' : sn.analysis_status === 'running' ? 'running' : s.analysis, done: sn.done, provisional: !sn.done, warnings: sn.warnings }
    }
  }
}

const EVENT_TYPES = ['status', 'answer_delta', 'answer_block_replaced', 'answer_completed', 'analysis_started', 'portrait_updated', 'risk_updated', 'completed', 'failed', 'cancelled'] as const

/** Подписка на /runs/{id}/events. EventSource сам переподключается с Last-Event-ID; при потере replay берём snapshot. */
export function useRunStream(runId: string | null, onEvent?: (ev: StreamEvent) => void) {
  const [state, dispatch] = useReducer(reduceStream, initialStream)
  const cb = useRef(onEvent)
  cb.current = onEvent
  useEffect(() => {
    if (!runId) return
    let closed = false
    const es = new EventSource(`/api/v1/runs/${runId}/events`)
    const push = (ev: StreamEvent) => { dispatch(ev); cb.current?.(ev) }
    es.onopen = () => push({ type: '__connection', data: { state: 'open' } })
    es.onerror = () => {
      if (closed) return
      push({ type: '__connection', data: { state: es.readyState === EventSource.CLOSED ? 'closed' : 'reconnecting' } })
      get<RunSnapshot>(`/runs/${runId}`).then((sn) => { if (!closed) push({ type: '__snapshot', data: sn }) }).catch(() => undefined)
    }
    for (const t of EVENT_TYPES) {
      es.addEventListener(t, (e) => {
        const data = JSON.parse((e as MessageEvent<string>).data) as never
        push({ type: t, data } as StreamEvent)
        if (t === 'completed' || t === 'failed' || t === 'cancelled') { closed = true; es.close(); push({ type: '__connection', data: { state: 'closed' } }) }
      })
    }
    es.addEventListener('snapshot', () => { get<RunSnapshot>(`/runs/${runId}`).then((sn) => push({ type: '__snapshot', data: sn })).catch(() => undefined) })
    return () => { closed = true; es.close() }
  }, [runId])
  return state
}
