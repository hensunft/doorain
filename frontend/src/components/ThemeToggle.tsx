import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme, type Theme } from '../lib/theme'

const OPTIONS: [Theme, string, typeof Sun][] = [
  ['light', 'Светлая тема', Sun],
  ['dark', 'Тёмная тема', Moon],
  ['system', 'Как в системе', Monitor],
]

export function ThemeToggle() {
  const [theme, setTheme] = useTheme()
  return (
    <div className="seg" role="group" aria-label="Тема оформления">
      {OPTIONS.map(([id, label, Icon]) => (
        <button key={id} type="button" className="seg-item !px-2" aria-pressed={theme === id} aria-label={label} title={label} onClick={() => setTheme(id)}>
          <Icon className="size-4" aria-hidden />
        </button>
      ))}
    </div>
  )
}
