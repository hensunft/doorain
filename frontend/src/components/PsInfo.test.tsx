import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PsInfo } from './PsInfo'

vi.mock('../lib/queries', () => ({ useSession: () => ({ data: { role: 'entrepreneur' } }) }))

const methodology = { measure: 'баллы 1–5', rules: ['P-подсказка', 'S-подсказка'], probability: { 1: 'редко' }, severity: { 1: 'мелко' }, levels: [] }

function setup() {
  const qc = new QueryClient()
  qc.setQueryData(['risk-methodology', 'entrepreneur'], methodology)
  render(<QueryClientProvider client={qc}><PsInfo what="p" sessionId="s" /><PsInfo what="s" sessionId="s" /></QueryClientProvider>)
  const p = screen.getByRole('button', { name: 'Что означает P' })
  const s = screen.getByRole('button', { name: 'Что означает S' })
  return { p, s }
}
const tips = () => screen.queryAllByRole('tooltip')
const near = { clientX: 0, clientY: 0 }  // jsdom: окно в (0,0) — выход «к окну», с задержкой
const far = { clientX: 5000, clientY: 5000 }

describe('PsInfo: одна подсказка на интерфейс', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('быстрые переходы P → S → P: максимум одно окно, текст последней иконки, старый таймер не закрывает новое', () => {
    const { p, s } = setup()
    for (const [from, to, text] of [[p, s, 'S-подсказка'], [s, p, 'P-подсказка'], [p, s, 'S-подсказка'], [s, p, 'P-подсказка']] as const) {
      fireEvent.mouseEnter(from)
      fireEvent.mouseLeave(from.parentElement!, near)  // отложенное закрытие старого
      fireEvent.mouseEnter(to)
      expect(tips()).toHaveLength(1)
      expect(tips()[0]).toHaveTextContent(text)
      act(() => { vi.advanceTimersByTime(1000) })
      expect(tips()).toHaveLength(1)
      expect(tips()[0]).toHaveTextContent(text)
    }
    fireEvent.mouseLeave(p.parentElement!, far)
    expect(tips()).toHaveLength(0)  // в пустое место — сразу, без таймера
  })

  it('выход к окну: короткая задержка, возврат в окно её отменяет', () => {
    const { p } = setup()
    fireEvent.mouseEnter(p)
    fireEvent.mouseLeave(p.parentElement!, near)
    act(() => { vi.advanceTimersByTime(100) })
    fireEvent.mouseEnter(p.parentElement!)
    act(() => { vi.advanceTimersByTime(1000) })
    expect(tips()).toHaveLength(1)
    fireEvent.mouseLeave(p.parentElement!, near)
    act(() => { vi.advanceTimersByTime(200) })
    expect(tips()).toHaveLength(0)
  })

  it('закреплённое окно: наведение на другую иконку не добавляет слой; клик переносит окно; Escape закрывает и возвращает фокус', () => {
    const { p, s } = setup()
    fireEvent.click(p)
    expect(screen.getByRole('dialog', { name: 'Что означает P' })).toBeInTheDocument()
    fireEvent.mouseEnter(s)
    expect(tips()).toHaveLength(0)
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    fireEvent.pointerDown(s)
    fireEvent.click(s)
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    expect(screen.getByRole('dialog', { name: 'Что означает S' })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryAllByRole('dialog')).toHaveLength(0)
    expect(s).toHaveFocus()
  })
})
