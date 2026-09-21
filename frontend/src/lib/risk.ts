import type { Level } from './api'

export const LEVEL_RU: Record<Level, string> = { low: 'Низкий', medium: 'Средний', high: 'Высокий', critical: 'Критический' }
export const LEVEL_ORDER: Level[] = ['low', 'medium', 'high', 'critical']
export const STATUS_RU: Record<string, string> = {
  open: 'Открыт',
  in_progress: 'В работе',
  resolved: 'Снят',
  needs_clarification: 'Нужно уточнение',
  not_applicable: 'Неприменим',
}
export const ROLE_RU = { student: 'Студент', entrepreneur: 'Предприниматель', expert: 'Эксперт' } as const
export const NODE_KIND_RU: Record<string, string> = { center: 'Центр', topic: 'Тема', question: 'Вопрос', norm: 'Норма', risk: 'Риск' }
export const RESULT_RU: Record<string, string> = { answered: 'Есть ответ', refused: 'Отказ', cancelled: 'Отменён', failed: 'Ошибка' }

export const levelOf = (score: number | null | undefined): Level | null =>
  score == null ? null : score <= 4 ? 'low' : score <= 9 ? 'medium' : score <= 15 ? 'high' : 'critical'

export const scoreLabel = (p: number | null, s: number | null, score: number | null) => (score == null ? 'не оценён' : `${p}×${s}=${score}`)

/** Цвет уровня как CSS-переменная токенов: в компонентах не должно быть литеральных цветов. */
export const levelVar = (level: Level | null | undefined): string =>
  `var(--risk-${level === 'medium' ? 'mid' : (level ?? 'none')})`
