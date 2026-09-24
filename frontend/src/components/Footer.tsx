import { Link } from 'react-router-dom'

export const DISCLAIMER_SHORT = 'Ответы носят информационный характер и не заменяют юридическую консультацию.'

/** Футер в потоке страницы: на входе, регистрации, правовых страницах и в приложении. Не фиксируется поверх чата и плана. */
export function Footer({ className = '' }: { className?: string }) {
  return (
    <footer className={`app-footer ${className}`}>
      <span>DoorAIn © {new Date().getFullYear()}</span>
      <nav aria-label="Правовая информация" className="flex flex-wrap gap-x-3 gap-y-1">
        <Link to="/privacy">Политика обработки персональных данных</Link>
        <Link to="/terms">Условия использования</Link>
        <Link to="/contacts">Контакты</Link>
      </nav>
      <span>{DISCLAIMER_SHORT}</span>
    </footer>
  )
}
