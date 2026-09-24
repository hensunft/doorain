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
/** Кто и как закрыл риск: в UI различаем «со слов пользователя» и подтверждённое фактами. */
export const RESOLVED_BY_RU: Record<string, string> = {
  closure_user_claim: 'Закрыт по вашему ответу — со слов пользователя, независимой проверки нет',
  closure_confirmed: 'Закрыт по ответу, подтверждённому фактами сессии',
  user_message: 'Снят по сообщению в диалоге — со слов пользователя, независимой проверки нет',
  owner_override: 'Закрыт владельцем без проверки ответа (записано в журнал)',
  owner: 'Снят вручную до введения проверки ответа',
}
export const ROLE_RU = { student: 'Студент', entrepreneur: 'Предприниматель', expert: 'Эксперт' } as const
export const NODE_KIND_RU: Record<string, string> = { center: 'Центр', topic: 'Тема', question: 'Вопрос', norm: 'Норма', risk: 'Риск' }
export const RESULT_RU: Record<string, string> = { answered: 'Есть ответ', refused: 'Отказ', cancelled: 'Отменён', failed: 'Ошибка' }

/** Уровень по порогам, которые отдаёт сервер (app/config/risk.yaml): своих порогов во frontend нет. */
export const levelOf = (score: number | null | undefined, t: number[] | undefined): Level | null =>
  score == null || !t || t.length < 3 ? null : score <= t[0]! ? 'low' : score <= t[1]! ? 'medium' : score <= t[2]! ? 'high' : 'critical'

export const scoreLabel = (p: number | null, s: number | null, score: number | null) => (score == null ? 'не оценён' : `${p}×${s}=${score}`)

/** Цвет уровня как CSS-переменная токенов: в компонентах не должно быть литеральных цветов. */
export const levelVar = (level: Level | null | undefined): string =>
  `var(--risk-${level === 'medium' ? 'mid' : (level ?? 'none')})`
