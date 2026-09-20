import { useCallback, useEffect, useState } from 'react'

/** localStorage — только удобства (размер панелей, свёрнутость). Любой доступ обёрнут в try/catch. */
export function useLocalState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw ? (JSON.parse(raw) as T) : initial
    } catch { return initial }
  })
  const set = useCallback((next: T) => {
    setV(next)
    try { localStorage.setItem(key, JSON.stringify(next)) } catch { /* без сохранения */ }
  }, [key])
  return [v, set]
}

export function useMedia(query: string): boolean {
  const [m, setM] = useState(() => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(query).matches : false))
  useEffect(() => {
    if (!window.matchMedia) return
    const mq = window.matchMedia(query)
    const on = () => setM(mq.matches)
    on()
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [query])
  return m
}

/** wide ≥1280, mid 768–1279, narrow <768 */
export function useLayoutMode(): 'wide' | 'mid' | 'narrow' {
  const wide = useMedia('(min-width: 1280px)')
  const mid = useMedia('(min-width: 768px)')
  return wide ? 'wide' : mid ? 'mid' : 'narrow'
}

export function useOnline(): boolean {
  const [on, setOn] = useState(() => navigator.onLine)
  useEffect(() => {
    const a = () => setOn(true), b = () => setOn(false)
    window.addEventListener('online', a); window.addEventListener('offline', b)
    return () => { window.removeEventListener('online', a); window.removeEventListener('offline', b) }
  }, [])
  return on
}
