import { X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'

interface Props {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  /** side — панель справа, drawer — узкая панель узла/риска (440 px), full — почти на весь экран */
  variant?: 'modal' | 'side' | 'drawer' | 'full'
  footer?: ReactNode
  overline?: string
}

/** Нативный <dialog>: focus trap, Escape и возврат фокуса обеспечивает браузер. */
export function Dialog({ open, onClose, title, children, variant = 'modal', footer, overline }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  const cls =
    variant === 'side' || variant === 'drawer'
      ? `drawer m-0 ml-auto h-dvh max-h-dvh ${variant === 'drawer' ? 'w-[min(440px,100vw)]' : 'w-[min(560px,100vw)]'} max-w-none rounded-none border-l border-[var(--glass-edge)]`
      : variant === 'full'
        ? 'm-auto h-[min(92dvh,900px)] w-[min(1280px,96vw)] max-w-none rounded-[var(--r-zone)] border border-[var(--glass-edge)]'
        : 'm-auto w-[min(560px,94vw)] rounded-[var(--r-zone)] border border-[var(--glass-edge)]'
  return (
    <dialog ref={ref} aria-labelledby={titleId} onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose() }} className={`${cls} p-0`}>
      {open && (
        <div className="flex h-full max-h-full flex-col">
          <header className="flex items-start justify-between gap-3 border-b border-line-soft px-5 py-3.5">
            <div className="min-w-0">
              {overline && <p className="overline mb-1">{overline}</p>}
              <h2 id={titleId} className={variant === 'drawer' ? 'body-l font-semibold' : 'text-h3'}>{title}</h2>
            </div>
            <button type="button" className="btn btn-tertiary btn-icon" aria-label="Закрыть" onClick={onClose}><X className="size-4" aria-hidden /></button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="flex flex-wrap justify-end gap-2 border-t border-line-soft px-5 py-3">{footer}</footer>}
        </div>
      )}
    </dialog>
  )
}
