import { Download, Search } from 'lucide-react'
import { useState } from 'react'
import { ThemeToggle } from '../../components/ThemeToggle'
import { Banner, EmptyState, ErrorNote, Skeleton } from '../../components/States'
import { Button, Field, RiskBadge, Spinner } from '../../components/ui'
import { LEVEL_ORDER, LEVEL_RU } from '../../lib/risk'
import type { Level } from '../../lib/api'

/** Библиотека компонентов: каждый элемент во всех состояниях. Доступна владельцу, нужна для приёмки визуальной системы. */
function Row({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="zone space-y-3">
      <div>
        <h2 className="display-s">{title}</h2>
        {hint && <p className="hint mt-1">{hint}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </section>
  )
}

const SURFACES: [string, string][] = [
  ['--bg', 'холст страницы'], ['--surface', 'панели и зоны'], ['--surface-2', 'полотно графа'],
  ['--surface-3', 'выделенные блоки'], ['--surface-alt', 'карточки'],
  ['--brand', 'центр слепка, кнопки'], ['--gold', 'нить диалога, фокус'],
]

export function StyleguidePage() {
  document.title = 'Библиотека компонентов — DoorAIn'
  const [seg, setSeg] = useState('map')
  const [bad, setBad] = useState(false)
  return (
    <div className="mx-auto max-w-5xl space-y-5 px-6 py-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="overline">Визуальная система</p>
          <h1 className="display-l">Библиотека компонентов</h1>
          <p className="hint mt-1">Один слой токенов: цвет, типографика, геометрия и движение берутся только отсюда. Литеральных цветов в компонентах нет.</p>
        </div>
        <ThemeToggle />
      </header>

      <Row title="Палитра" hint="Значения меняются вместе с темой — переменные одни и те же.">
        {SURFACES.map(([v, use]) => (
          <div key={v} className="w-36">
            <div className="h-12 rounded-lg border border-line" style={{ background: `var(${v})` }} />
            <p className="mono-m mt-1">{v}</p>
            <p className="caption">{use}</p>
          </div>
        ))}
      </Row>

      <Row title="Уровни риска" hint="Уровень никогда не кодируется одним цветом: рядом число P × S и словесный уровень.">
        {LEVEL_ORDER.map((l: Level) => (
          <div key={l} className="w-40 space-y-1">
            <div className="h-10 rounded-lg" style={{ background: `var(--risk-${l === 'medium' ? 'mid' : l})` }} />
            <RiskBadge level={l} score={l === 'low' ? 3 : l === 'medium' ? 8 : l === 'high' ? 12 : 20} />
            <p className="caption">{LEVEL_RU[l]}</p>
          </div>
        ))}
        <div className="w-40 space-y-1">
          <div className="h-10 rounded-lg" style={{ background: 'var(--risk-none)' }} />
          <RiskBadge level={null} />
          <p className="caption">Нет рисков или мало данных — не «безопасно»</p>
        </div>
      </Row>

      <Row title="Типографика">
        <div className="space-y-2">
          <p className="display-l">Цифровой слепок — display-l 30</p>
          <p className="display-m">Заголовок раздела — display-m 22</p>
          <p className="display-s">Заголовок зоны — display-s 17</p>
          <p className="body-l">Основной текст интерфейса — body-l 14</p>
          <p className="body-m">Сообщения диалога — body-m 13</p>
          <p className="body-s">Пояснения в карточках — body-s 12</p>
          <p className="caption">Подписи и легенда — caption 11,5</p>
          <p className="overline">Метка блока — overline 10</p>
          <p className="mono-m">152-ФЗ, ст. 22, ч. 1 · ред. от 08.08.2024 — mono-m</p>
          <p className="mono-l">4 × 3 = 12 — mono-l</p>
        </div>
      </Row>

      <Row title="Кнопки" hint="Состояния: обычное, наведение, фокус (Tab), отключённое.">
        <Button variant="primary">Первичная</Button>
        <Button>Вторичная</Button>
        <Button variant="quiet">Тихая</Button>
        <Button variant="danger">Опасная</Button>
        <Button variant="primary" disabled>Отключена</Button>
        <button className="btn btn-icon" aria-label="Скачать"><Download className="size-4" aria-hidden /></button>
        <Spinner label="Загружаем…" />
      </Row>

      <Row title="Переключатель режимов">
        <div className="seg" role="tablist" aria-label="Режим портрета">
          {([['map', 'Карта тем'], ['timeline', 'Хронология'], ['plan', 'План-схема']] as const).map(([id, label]) => (
            <button key={id} role="tab" className="seg-item" aria-selected={seg === id} onClick={() => setSeg(id)}>{label}</button>
          ))}
        </div>
      </Row>

      <Row title="Поля ввода">
        <div className="w-64"><Field id="sg-ok" label="Обычное поле" hint="Подсказка под полем"><input id="sg-ok" className="input" placeholder="Введите запрос" /></Field></div>
        <div className="w-64"><Field id="sg-bad" label="Поле с ошибкой"><input id="sg-bad" className="input" aria-invalid={bad} value={bad ? 'нет' : ''} onChange={() => undefined} /></Field></div>
        <Button onClick={() => setBad(!bad)}>Показать ошибку</Button>
        <label className="relative">
          <span className="sr-only">Поиск</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
          <input className="input !w-56 !pl-9" placeholder="Поиск" />
        </label>
      </Row>

      <Row title="Чипы, основания и врезки">
        <button className="chip-norm">152-ФЗ, ст. 22, ч. 1</button>
        <span className="chip-norm">КоАП РФ, ст. 13.11</span>
        <span className="chip">обычный чип</span>
        <span className="chip risk-medium">средний</span>
        <button className="inline-note" style={{ ['--level' as string]: 'var(--risk-high)' }}>
          Добавлен риск: обработка ПДн без уведомления · 12
        </button>
      </Row>

      <Row title="Сообщения диалога">
        <div className="w-full max-w-md space-y-2">
          <div className="bubble-user ml-auto w-fit">Мы храним e-mail и ФИО учеников в CRM. Нужно ли уведомлять Роскомнадзор?</div>
          <div className="bubble-agent w-fit">Да. ФИО и адрес электронной почты — персональные данные, а школа выступает оператором.</div>
        </div>
      </Row>

      <Row title="Карточка риска">
        <article className="card card-risk w-full max-w-lg" style={{ ['--level' as string]: 'var(--risk-critical)' }}>
          <div className="flex items-start justify-between gap-3">
            <h3 className="body-l font-semibold">Первичная запись ПДн на зарубежный сервер</h3>
            <span className="badge-level" style={{ ['--level' as string]: 'var(--risk-critical)' }}>20</span>
          </div>
          <p className="mono-m mt-1 text-muted">ч. 5 ст. 18 152-ФЗ · вопрос №2</p>
          <p className="body-s mt-2">Перенести первичную запись в базу на территории РФ, зарубежную CRM использовать как вторичную.</p>
          <div className="seg mt-3" role="group" aria-label="Статус риска">
            <button className="seg-item" aria-pressed>Открыт</button>
            <button className="seg-item">В работе</button>
            <button className="seg-item">Закрыт</button>
          </div>
        </article>
      </Row>

      <Row title="Карточка наведения">
        <div className="tooltip-card w-80" style={{ ['--level' as string]: 'var(--risk-high)' }}>
          <div className="p-3">
            <p className="overline">Вопрос №1 · 21 сентября, 14:02</p>
            <p className="body-l mt-1 font-semibold">Нужно ли уведомлять Роскомнадзор, если мы храним e-mail учеников?</p>
            <p className="body-s mt-1 text-muted">Вывод: уведомление обязательно, до начала обработки.</p>
            <p className="mono-m mt-2" style={{ color: 'var(--risk-high)' }}>2 нормы · 1 риск · высокий (12)</p>
          </div>
        </div>
      </Row>

      <Row title="Состояния данных">
        <div className="w-64"><Skeleton lines={3} /></div>
        <div className="w-72"><Banner tone="warn">Предупреждение: демонстрационные данные.</Banner></div>
        <div className="w-72"><ErrorNote error={new Error('Не удалось загрузить')} onRetry={() => undefined} /></div>
        <div className="w-80"><EmptyState title="Портрет пока пуст">После первого вопроса здесь появятся темы, нормы и связи.</EmptyState></div>
      </Row>

      <p className="caption">Ответы носят информационный характер и не заменяют профессиональную юридическую помощь.</p>
    </div>
  )
}
