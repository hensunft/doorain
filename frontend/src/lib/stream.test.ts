import { describe, expect, it } from 'vitest'
import type { Block } from './api'
import { initialStream, reduceStream, type StreamEvent, type StreamState } from './stream'

const blk = (id: string, text: string, version = 1, extra: Partial<Block> = {}): Block => ({ id, version, kind: 'claim', text, citation_ids: [], markers: [], state: 'verified', removed: false, ...extra }) as Block
const run = (events: StreamEvent[], s: StreamState = initialStream) => events.reduce(reduceStream, s)

describe('reduceStream', () => {
  it('накапливает блоки и не дублирует один и тот же id', () => {
    const s = run([
      { type: 'answer_delta', data: { block: blk('b1', 'один') } },
      { type: 'answer_delta', data: { block: blk('b2', 'два') } },
      { type: 'answer_delta', data: { block: blk('b1', 'один') } },
    ])
    expect(s.blocks.map((b) => b.id)).toEqual(['b1', 'b2'])
    expect(s.provisional).toBe(true)
  })

  it('answer_block_replaced заменяет блок, старая версия не перезаписывает новую', () => {
    let s = run([{ type: 'answer_delta', data: { block: blk('b1', 'старое') } }, { type: 'answer_block_replaced', data: { block: blk('b1', 'исправлено', 2) } }])
    expect(s.blocks[0]?.text).toBe('исправлено')
    s = run([{ type: 'answer_delta', data: { block: blk('b1', 'опоздавшее старое', 1) } }], s)
    expect(s.blocks[0]?.text).toBe('исправлено')
  })

  it('removed=true убирает блок из буфера', () => {
    const s = run([{ type: 'answer_delta', data: { block: blk('b1', 'x') } }, { type: 'answer_block_replaced', data: { block: blk('b1', '', 2, { removed: true }) } }])
    expect(s.blocks).toHaveLength(0)
  })

  it('answer_completed полностью заменяет предварительный буфер каноническим ответом', () => {
    const s = run([
      { type: 'answer_delta', data: { block: blk('b1', 'предварительный') } },
      { type: 'answer_delta', data: { block: blk('b9', 'потом отброшен') } },
      { type: 'answer_completed', data: { blocks: [blk('b1', 'канонический')], answer_status: 'validated', warnings: ['w'] } },
    ])
    expect(s.blocks.map((b) => b.text)).toEqual(['канонический'])
    expect(s.provisional).toBe(false)
    expect(s.final).toBe('validated')
    expect(s.warnings).toEqual(['w'])
  })

  it('перезапуск run очищает частичный текст', () => {
    const s = run([{ type: 'answer_delta', data: { block: blk('b1', 'x') } }, { type: 'status', data: { stage: 'restarted', message: 'повтор' } }])
    expect(s.blocks).toHaveLength(0)
  })

  it('аналитика: сбой не стирает проверенный ответ', () => {
    const s = run([
      { type: 'answer_completed', data: { blocks: [blk('b1', 'ответ')], answer_status: 'validated' } },
      { type: 'analysis_started', data: {} },
      { type: 'status', data: { stage: 'analysis_failed', message: 'не выполнена' } },
      { type: 'completed', data: { answer_status: 'validated', analysis_status: 'failed' } },
    ])
    expect(s.analysis).toBe('failed')
    expect(s.blocks).toHaveLength(1)
    expect(s.done).toBe(true)
    expect(s.final).toBe('validated')
  })

  it('отмена ответа: итог cancelled, отмена аналитики не меняет итог ответа', () => {
    const a = run([{ type: 'answer_delta', data: { block: blk('b1', 'частично') } }, { type: 'cancelled', data: { blocks: [blk('b1', 'частично')] } }])
    expect(a.final).toBe('cancelled')
    const b = run([{ type: 'answer_completed', data: { blocks: [], answer_status: 'validated' } }, { type: 'cancelled', data: { phase: 'analysis' } }])
    expect(b.final).toBe('validated')
  })

  it('snapshot после потери replay восстанавливает состояние', () => {
    const s = run([{ type: '__snapshot', data: { run_id: 'r', session_id: 's', answer_status: 'refused', analysis_status: 'not_started', warnings: [], blocks: [blk('b1', 'отказ', 1, { kind: 'refusal' })], last_event_id: 3, done: true, user_message_id: 'u', timings: {} } }])
    expect(s.final).toBe('refused')
    expect(s.done).toBe(true)
    expect(s.blocks[0]?.kind).toBe('refusal')
  })

  it('failed сохраняет блоки и показывает ошибку', () => {
    const s = run([{ type: 'failed', data: { message: 'Модель недоступна' } }])
    expect(s.final).toBe('failed')
    expect(s.error).toBe('Модель недоступна')
  })
})
