import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

/** Вертикальный разделитель зон. Объявлен на уровне модуля: тип компонента стабилен, DOM-узел не пересоздаётся при смене
 *  ширины и не теряет pointer capture. Ширина меняется только пока нажата основная кнопка (или удерживается касание/перо). */
export function Splitter({ label, value, min, max, dir, onChange }: {
  label: string
  value: number
  min: number
  max: number
  dir: 1 | -1  // 1 — движение вправо расширяет зону слева от разделителя, -1 — зону справа
  onChange: (v: number) => void
}) {
  const drag = useRef<{ x: number; start: number; id: number } | null>(null)
  const el = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState(false)
  const clamp = (v: number) => Math.round(Math.max(min, Math.min(max, v)))
  const end = () => {
    const d = drag.current
    drag.current = null
    if (d && el.current?.hasPointerCapture(d.id)) el.current.releasePointerCapture(d.id)
    setActive(false)
  }
  useEffect(() => () => { drag.current = null }, [])
  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return
    e.preventDefault()
    drag.current = { x: e.clientX, start: value, id: e.pointerId }
    e.currentTarget.setPointerCapture(e.pointerId)
    setActive(true)
  }
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    if (e.pointerType === 'mouse' && (e.buttons & 1) === 0) return end()  // кнопку отпустили вне окна: pointerup мог не прийти
    onChange(clamp(d.start + dir * (e.clientX - d.x)))
  }
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 60 : 20
    const next = e.key === 'ArrowRight' ? value + dir * step : e.key === 'ArrowLeft' ? value - dir * step : e.key === 'Home' ? min : e.key === 'End' ? max : null
    if (next === null) return
    e.preventDefault()
    onChange(clamp(next))
  }
  return (
    <div
      ref={el} role="separator" aria-orientation="vertical" aria-label={label} aria-valuenow={value} aria-valuemin={min} aria-valuemax={max} tabIndex={0}
      data-active={active || undefined}
      onPointerDown={down} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end} onKeyDown={key}
      className="splitter group flex w-8 cursor-col-resize touch-none select-none justify-center bg-page"
    >
      <span className="h-full w-0.5 rounded-full transition-colors group-hover:bg-line-strong group-focus-visible:bg-gold group-data-[active]:bg-gold" />
    </div>
  )
}
