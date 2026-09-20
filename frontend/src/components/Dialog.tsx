import { X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'

interface Props {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  /** side — панель справа (drawer), full — почти на весь экран */
  variant?: 'modal' | 'side' | 'full'
  footer?: ReactNode
}

/** Нативный <dialog>: focus trap, Escape и возврат фокуса обеспечивает браузер. */
export function Dialog({ open, onClose, title, children, variant = 'modal', footer }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  const cls =
    variant === 'side'
      ? 'm-0 ml-auto h-dvh max-h-dvh w-[min(560px,100vw)] max-w-none rounded-none border-l border-line'
      : variant === 'full'
        ? 'm-auto h-[min(92dvh,900px)] w-[min(1280px,96vw)] max-w-none rounded-lg border border-line'
        : 'm-auto w-[min(560px,94vw)] rounded-lg border border-line'
  return (
    <dialog ref={ref} aria-labelledby={titleId} onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose() }} className={`${cls} bg-canvas p-0 text-ink`}>
      {open && (
        <div className="flex h-full max-h-full flex-col">
          <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-3">
            <h2 id={titleId} className="text-h3">{title}</h2>
            <button type="button" className="btn btn-quiet btn-icon" aria-label="Закрыть" onClick={onClose}><X className="size-4" aria-hidden /></button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
        </div>
      )}
    </dialog>
  )
}
