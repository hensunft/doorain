import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { components } from '../../lib/api-types'
import type { Risk } from '../../lib/api'
import { keys } from '../../lib/queries'
import { SelectionProvider } from '../../lib/selection'
import { RiskMatrix } from './RiskMatrix'

type Cell = components['schemas']['MatrixCell']
const lv = (x: number) => (x <= 4 ? 'low' : x <= 9 ? 'medium' : x <= 15 ? 'high' : 'critical') as Cell['level']
const cells: Cell[] = [5, 4, 3, 2, 1].flatMap((p) => [1, 2, 3, 4, 5].map((s) => ({
  p, s, level: lv(p * s), count: p === 4 && s === 3 ? 2 : 0,
  risks: p === 4 && s === 3 ? [{ id: 'r1', title: 'ПДн на зарубежном сервере' }, { id: 'r2', title: 'Нет уведомления РКН' }] : [],
})))
const risks = [{ id: 'r1', norms: ['152-ФЗ, ст. 18 ч. 5'], status: 'open' }, { id: 'r2', norms: [], status: 'in_progress' }] as unknown as Risk[]

function setup() {
  const qc = new QueryClient()
  qc.setQueryData([...keys.risks('s1'), 'matrix'], cells)
  render(<QueryClientProvider client={qc}><SelectionProvider><RiskMatrix sessionId="s1" risks={risks} thresholds={[4, 9, 15]} /></SelectionProvider></QueryClientProvider>)
}

describe('матрица рисков', () => {
  it('в ячейке только число открытых рисков либо пусто; цвет — по уровню координат', () => {
    setup()
    const grid = screen.getAllByRole('gridcell')
    expect(grid).toHaveLength(25)
    const filled = grid.filter((c) => c.dataset['filled'] === 'true')
    expect(filled).toHaveLength(1)
    expect(filled[0]).toHaveTextContent(/^2$/)
    expect(filled[0]).toHaveAttribute('data-level', 'high')
    expect(grid.filter((c) => c.dataset['filled'] !== 'true').every((c) => c.textContent === '')).toBe(true)
    expect(grid.find((c) => c.getAttribute('aria-label')?.startsWith('P5 × S5'))).toHaveAttribute('data-level', 'critical')
    expect(screen.getByLabelText('Легенда уровней')).toHaveTextContent('Высокий 10–15')
  })

  it('клик по ячейке раскрывает её риски с нормой и статусом', async () => {
    setup()
    await userEvent.click(screen.getByRole('gridcell', { name: /P4 × S3/ }))
    const list = screen.getByRole('list', { name: 'Риски ячейки P4 × S3' })
    expect(list).toHaveTextContent('ПДн на зарубежном сервере')
    expect(list).toHaveTextContent('152-ФЗ, ст. 18 ч. 5')
    expect(list).toHaveTextContent('В работе')
  })
})
