import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme, type Theme } from '../lib/theme'

const OPTIONS: [Theme, string, typeof Sun][] = [
  ['light', 'Светлая тема', Sun],
  ['dark', 'Тёмная тема', Moon],
  ['system', 'Как в системе', Monitor],
]

/** Переключатель темы. compact — одна кнопка для свёрнутой боковой панели: переключает по кругу, подпись в aria-label и title. */
export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useTheme()
  if (compact) {
    const i = OPTIONS.findIndex(([id]) => id === theme)
    const [, label, Icon] = OPTIONS[i] ?? OPTIONS[2]!
    const next = OPTIONS[(i + 1) % OPTIONS.length]!
    const hint = `Тема: ${label.toLowerCase()}. Переключить на: ${next[1].toLowerCase()}`
    return (
      <button type="button" className="btn btn-tertiary btn-icon" aria-label={hint} title={hint} onClick={() => setTheme(next[0])}>
        <Icon className="size-4" aria-hidden />
      </button>
    )
  }
  return (
    <div className="seg" role="group" aria-label="Тема оформления">
      {OPTIONS.map(([id, label, Icon]) => (
        <button key={id} type="button" className="seg-item min-w-11 justify-center" aria-pressed={theme === id} aria-label={label} title={label} onClick={() => setTheme(id)}>
          <Icon className="size-4" aria-hidden />
        </button>
      ))}
    </div>
  )
}
