import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'system'
const KEY = 'doorain.theme'

/** Тема применяется атрибутом на <html>; «system» снимает атрибут и отдаёт выбор prefers-color-scheme. */
export function applyTheme(t: Theme): void {
  const el = document.documentElement
  if (t === 'system') el.removeAttribute('data-theme')
  else el.setAttribute('data-theme', t)
}

export function readTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'system'
  } catch {
    return 'system' // приватный режим или запрет на хранилище: тема берётся из системной настройки
  }
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setState] = useState<Theme>(readTheme)
  useEffect(() => { applyTheme(theme) }, [theme])
  const set = useCallback((t: Theme) => {
    setState(t)
    try { localStorage.setItem(KEY, t) } catch { /* хранилище недоступно — тема действует до перезагрузки */ }
  }, [])
  return [theme, set]
}
