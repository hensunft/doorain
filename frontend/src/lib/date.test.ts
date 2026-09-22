import { expect, it } from 'vitest'

import { todayISO } from './date'

it('todayISO отдаёт местную дату, а не UTC', () => {
  const d = new Date()
  const two = (n: number) => String(n).padStart(2, '0')
  expect(todayISO()).toBe(`${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`)
})
