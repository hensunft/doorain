import { render } from '@testing-library/react'
import favicon from '../../public/favicon.svg?raw'
import { DOOR_PATHS, DoorMark } from './DoorMark'

describe('знак DoorAIn', () => {
  it('цвет — из темы, а не зашитый в файл: коробка currentColor + text-ink, ручка --brand-line; знак декоративный', () => {
    const { container } = render(<DoorMark />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.getAttribute('stroke')).toBe('currentColor')
    expect(svg.getAttribute('class')).toContain('text-ink')
    expect(container.querySelector('circle')!.getAttribute('style')).toContain('var(--brand-line)')
  })

  it('favicon повторяет геометрию и имеет вариант для тёмной системной темы', () => {
    for (const d of DOOR_PATHS) expect(favicon).toContain(`d="${d}"`)
    expect(favicon).toMatch(/@media \(prefers-color-scheme:\s*dark\)/)
  })
})
