/** Геометрия знака DoorAIn (сетка 32 × 32); та же — в public/favicon.svg (сверяет DoorMark.test.tsx). */
export const DOOR_PATHS = ['M8 28V6.5a1.5 1.5 0 0 1 1.3-1.5l10-1.6A1.5 1.5 0 0 1 21 4.9V28', 'M4 28h24'] as const

/** Знак-дверь: коробка — цветом текста текущей темы (ручное переключение темы работает, в отличие от <img>),
 *  ручка — бордовая линия бренда. Декоративный: доступное имя даёт ссылка или соседнее название. */
export function DoorMark({ className = 'size-6' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={`shrink-0 text-ink ${className}`} fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      {DOOR_PATHS.map((d) => <path key={d} d={d} />)}
      <circle cx="17.3" cy="17" r="1.5" stroke="none" style={{ fill: 'var(--brand-line)' }} />
    </svg>
  )
}
