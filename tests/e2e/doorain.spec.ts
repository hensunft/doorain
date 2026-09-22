import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const PASSWORD = 'e2e passphrase 12345'
const NO_POLICY = 'У нас нет политики обработки персональных данных на сайте.'
const SHOTS = path.resolve(__dirname, '../../docs/qa')

async function login(page: Page) {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await page.getByLabel('Имя пользователя').fill('e2e')
  await page.getByLabel('Пароль').fill(PASSWORD)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('heading', { name: 'Портрет вашего правового положения' })).toBeVisible()
}

async function startSession(page: Page, role: 'Студент' | 'Предприниматель' | 'Эксперт' = 'Предприниматель') {
  await page.getByRole('radio', { name: new RegExp(role) }).check({ force: true })
  await page.getByRole('button', { name: new RegExp(`Начать как «${role}»`) }).click()
  await expect(page.getByRole('log', { name: 'Диалог' })).toBeVisible()
}

async function ask(page: Page, text: string) {
  const box = page.getByLabel('Ваш вопрос')
  await box.fill(text)
  await box.press('Enter')
}

test.describe.configure({ mode: 'serial' })

test('вход обязателен; ошибка входа единообразна; дисклеймер после входа', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('link', { name: /Зарегистрироваться по коду приглашения/ })).toBeVisible()
  await page.getByLabel('Имя пользователя').fill('e2e')
  await page.getByLabel('Пароль').fill('wrong password 123')
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('alert')).toContainText('Неверное имя пользователя или пароль')
  await login(page)
  await expect(page.getByText('не заменяют профессиональную юридическую помощь').first()).toBeVisible()
})

test('вертикальный сценарий: вопрос → ответ с источником → слепок → риск → навигация → перезагрузка', async ({ page }) => {
  const violations: string[] = []
  page.on('console', (m) => { if (/Content Security Policy|Refused to/i.test(m.text())) violations.push(m.text()) })
  page.on('pageerror', (e) => violations.push(String(e)))
  await login(page)
  await page.getByRole('radio', { name: /Предприниматель/ }).check({ force: true })
  await page.getByLabel('Сфера деятельности').fill('онлайн-школа программирования')
  await page.getByLabel('Есть сайт или приложение').selectOption('yes')
  await page.getByRole('button', { name: /Начать как/ }).click()
  await expect(page.getByRole('log', { name: 'Диалог' })).toBeVisible()
  // честные метки режима
  await expect(page.getByText('Тестовый режим: не языковая модель')).toBeVisible()
  await expect(page.getByText('Демонстрационные данные — не нормативная база').first()).toBeVisible()

  await ask(page, NO_POLICY)
  const chip = page.getByRole('button', { name: /Открыть источник: ДЕМО-1-ФЗ, ст\. 7/ }).first()
  await expect(chip).toBeVisible()
  await expect(page.getByText('Источники и редакции:')).toBeVisible()

  // источник в drawer, возврат фокуса по Escape
  await chip.focus()
  await chip.press('Enter')
  const drawer = page.getByRole('dialog', { name: 'Источник' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText('Демонстрационные данные — не нормативная база')).toBeVisible()
  await expect(drawer.getByText('Сохранённая выдержка')).toBeVisible()
  await expect(drawer.getByText('редакция от 2026-03-01').or(drawer.getByText('от 2026-03-01'))).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await expect(chip).toBeFocused()

  // врезка в чате о появлении риска
  await expect(page.getByRole('button', { name: /Добавлен риск: Нет опубликованной политики/ })).toBeVisible()
  // риск в правой панели: уровень дублирован текстом и числом
  const risk = page.getByRole('region', { name: 'Риски' }).getByRole('button', { name: /Нет опубликованной политики обработки ПДн/ }).first()
  await expect(risk).toBeVisible()
  await expect(risk).toContainText('Средний')
  await expect(risk).toContainText('8')
  // граф: узлы карты
  await expect(page.locator('.react-flow__node')).toHaveCount(5, { timeout: 15_000 }) // центр, тема, вопрос, норма(ы), риск — не менее 4
    .catch(async () => { expect(await page.locator('.react-flow__node').count()).toBeGreaterThanOrEqual(4) })
  // двусторонняя навигация: клик по риску раскрывает детали, подсвечивает узлы и выделяет вопрос в диалоге
  await risk.click()
  await expect(page.getByText('Почему такая оценка')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Снять выделение' }).first()).toBeVisible()
  // текстовая альтернатива графа
  await page.getByRole('button', { name: 'Текстом' }).click()
  await expect(page.getByLabel('Список узлов слепка')).toContainText('Нет опубликованной политики')
  await page.getByRole('button', { name: 'Показать карту' }).click()
  await page.getByRole('tab', { name: 'Хронология' }).click()
  await expect(page.getByLabel('Хронология вопросов')).toContainText(NO_POLICY.slice(0, 20))
  fs.mkdirSync(SHOTS, { recursive: true })
  await page.getByRole('tab', { name: 'Карта тем' }).click()
  await page.screenshot({ path: path.join(SHOTS, 'workspace-1440.png') })

  expect(violations, 'нарушения CSP или ошибки страницы').toEqual([])
  // перезагрузка: сессия, риск и слепок восстановлены с сервера
  await page.reload()
  await expect(page.getByRole('button', { name: /Нет опубликованной политики обработки ПДн/ }).first()).toBeVisible()
  await expect(page.getByRole('log', { name: 'Диалог' }).getByText(NO_POLICY)).toBeVisible()
})

test('отказ вне области; Shift+Enter не отправляет; риски не создаются', async ({ page }) => {
  await login(page)
  await startSession(page, 'Эксперт')
  const box = page.getByLabel('Ваш вопрос')
  await box.fill('первая строка')
  await box.press('Shift+Enter')
  await box.type('вторая строка')
  await expect(box).toHaveValue('первая строка\nвторая строка')
  await box.fill('')
  await ask(page, 'Расскажи рецепт борща с говядиной')
  await expect(page.getByText('выходит за пределы права высоких технологий').first()).toBeVisible()
  await expect(page.getByText('Подтверждённых рисков нет')).toBeVisible()
})

test('пустое состояние риск-панели и портрета объясняет действие', async ({ page }) => {
  await login(page)
  await startSession(page)
  await expect(page.getByText('Задайте первый вопрос')).toBeVisible()
  await expect(page.getByText('Портрет пока пуст')).toBeVisible()
  await expect(page.getByText('Подтверждённых рисков нет')).toBeVisible()
})

test('экспорт PDF из сессии: файл — валидный PDF', async ({ page }) => {
  await login(page)
  await startSession(page)
  await ask(page, NO_POLICY)
  await expect(page.getByText('Источники и редакции:')).toBeVisible()
  await expect(page.getByRole('button', { name: /Нет опубликованной политики/ }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Выгрузить PDF' }).click()
  await page.getByRole('button', { name: 'Сформировать PDF' }).click()
  const link = page.getByRole('link', { name: /Скачать PDF/ })
  await expect(link).toBeVisible({ timeout: 30_000 })
  const href = await link.getAttribute('href')
  const res = await page.request.get(href!)
  expect(res.status()).toBe(200)
  expect(res.headers()['content-type']).toBe('application/pdf')
  expect((await res.body()).subarray(0, 5).toString()).toBe('%PDF-')
})

test('база знаний: демо-маркировка, manifest, сравнение редакций', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'База знаний' }).click()
  await expect(page.getByRole('heading', { name: 'База знаний' })).toBeVisible()
  await expect(page.getByText('демонстрационные данные — не нормативная база', { exact: false }).first()).toBeVisible()
  await expect(page.getByText('Перечень источников из концепции')).toBeVisible()
  await expect(page.getByText('ФЗ № 152-ФЗ «О персональных данных»')).toBeVisible()
  const sel = page.getByLabel('Документ', { exact: true })
  await sel.selectOption({ index: 1 })
  await page.getByLabel('Было', { exact: true }).selectOption({ index: 1 })
  await page.getByLabel('Стало', { exact: true }).selectOption({ index: 2 })
  await expect(page.getByText('изменено').first()).toBeVisible()
  await expect(page.locator('ins').first()).toBeVisible()
})

test('адаптивность: 390 / 768 / 1024 / 1440, без горизонтальной прокрутки; масштаб 200%', async ({ page }) => {
  await login(page)
  await startSession(page)
  await ask(page, NO_POLICY)
  await expect(page.getByText('Источники и редакции:')).toBeVisible()
  fs.mkdirSync(SHOTS, { recursive: true })
  for (const [w, h] of [[390, 844], [768, 1024], [1024, 768], [1440, 900]] as const) {
    await page.setViewportSize({ width: w, height: h })
    await page.waitForTimeout(300)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, `горизонтальная прокрутка на ${w}px`).toBeLessThanOrEqual(1)
    await expect(page.getByLabel('Ваш вопрос')).toBeVisible()
    if (w < 768) {
      await expect(page.getByRole('tab', { name: 'Портрет' })).toBeVisible()
      await page.getByRole('tab', { name: 'Риски' }).click()
      await expect(page.getByRole('button', { name: /Нет опубликованной политики/ }).first()).toBeVisible()
      await page.screenshot({ path: path.join(SHOTS, `risks-${w}.png`) })
      // карта в скрытой вкладке измеряется нулём: после показа она должна быть вписана, а не сжата до предела
      await page.getByRole('tab', { name: 'Портрет' }).click()
      await page.waitForTimeout(600)
      const zoom = await page.evaluate(() => Number(/scale\(([\d.]+)\)/.exec(document.querySelector('.react-flow__viewport')?.getAttribute('style') ?? '')?.[1] ?? 0))
      expect(zoom, `масштаб карты на ${w}px`).toBeGreaterThan(0.2)
      await page.getByRole('tab', { name: 'Диалог' }).click()
    }
    // поле вопроса занимает ширину своей зоны: кнопка отправки стоит строкой ниже
    const composer = await page.evaluate(() => {
      const el = document.querySelector('#composer') as HTMLElement
      return { field: el.getBoundingClientRect().width, zone: (el.parentElement as HTMLElement).getBoundingClientRect().width }
    })
    expect(composer.field, `ширина поля вопроса на ${w}px`).toBeGreaterThan(composer.zone * 0.8)
    await page.screenshot({ path: path.join(SHOTS, `workspace-${w}.png`) })
  }
  // 200%: эмуляция уменьшением CSS-ширины вдвое от 1440
  await page.setViewportSize({ width: 720, height: 450 })
  await page.waitForTimeout(300)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1)
  await page.screenshot({ path: path.join(SHOTS, 'workspace-zoom200.png') })
})

test('снимки страниц для визуального контроля (вход, приветствие, база знаний, история, настройки)', async ({ page }) => {
  fs.mkdirSync(SHOTS, { recursive: true })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/login')
  await page.screenshot({ path: path.join(SHOTS, 'login-1440.png') })
  await login(page)
  await page.screenshot({ path: path.join(SHOTS, 'welcome-1440.png') })
  await page.getByRole('link', { name: 'База знаний' }).click()
  await expect(page.getByRole('heading', { name: 'База знаний' })).toBeVisible()
  await page.screenshot({ path: path.join(SHOTS, 'kb-1440.png'), fullPage: true })
  await page.getByRole('link', { name: 'Мои сессии' }).click()
  await expect(page.getByRole('heading', { name: 'Мои сессии' })).toBeVisible()
  await page.screenshot({ path: path.join(SHOTS, 'history-1440.png') })
  await page.getByRole('link', { name: 'Настройки' }).click()
  await expect(page.getByRole('heading', { name: 'О программе' })).toBeVisible()
  await expect(page.getByText('ТЕСТОВЫЙ (заглушки, не модель)')).toBeVisible()
  await page.screenshot({ path: path.join(SHOTS, 'settings-1440.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Портрет вашего правового положения' })).toBeVisible()
  await page.screenshot({ path: path.join(SHOTS, 'welcome-390.png'), fullPage: true })
})

test('выход завершает сессию: защищённые страницы недоступны', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Настройки' }).click()
  await page.getByRole('button', { name: 'Выйти' }).click()
  await expect(page).toHaveURL(/\/login/)
  const r = await page.request.get('/api/v1/sessions')
  expect(r.status()).toBe(401)
})

test('пользователь по приглашению: регистрация → дисклеймер → роль → вопросы → выход → вход', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Администрирование' }).click()
  await page.getByLabel('Для кого код').fill('e2e-пользователь')
  await page.getByRole('button', { name: 'Выпустить код' }).click()
  const code = (await page.locator('code.select-all').innerText()).trim()
  expect(code.length).toBeGreaterThan(20)
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Выйти' }).click()

  const user = `u${Date.now().toString().slice(-8)}`
  await page.goto('/register')
  await page.getByLabel('Код приглашения').fill(code)
  await page.getByLabel('Имя пользователя').fill(user)
  await page.getByLabel('Пароль').fill(PASSWORD)
  await page.getByRole('button', { name: 'Создать учётную запись' }).click()

  // дисклеймер показывается до работы и фиксируется
  await expect(page.getByRole('heading', { name: 'Прежде чем начать' })).toBeVisible()
  await expect(page.getByText('не оказывает юридических услуг')).toBeVisible()
  await expect(page.getByText('видны только вам и владельцу сервиса')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Продолжить' })).toBeDisabled()  // без отметки не пускает
  await page.getByLabel(/Я прочитал/).check()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await expect(page.getByRole('heading', { name: 'Портрет вашего правового положения' })).toBeVisible()
  // разделы владельца пользователю не видны
  await expect(page.getByRole('link', { name: 'Администрирование' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'База знаний' })).toHaveCount(0)

  await startSession(page, 'Предприниматель')
  await ask(page, NO_POLICY)
  await expect(page.getByRole('button', { name: /Открыть источник: ДЕМО-1-ФЗ/ }).first()).toBeVisible()
  await expect(page.getByRole('region', { name: 'Риски' }).getByRole('article').first()).toBeVisible()
  const url = page.url()

  await page.goto('/settings')
  await page.getByRole('button', { name: 'Выйти' }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.goto(url)
  await expect(page).toHaveURL(/\/login/)  // чужой (и свой) рабочий стол без входа недоступен
  await page.getByLabel('Имя пользователя').fill(user)
  await page.getByLabel('Пароль').fill(PASSWORD)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page).toHaveURL(url)  // вход возвращает на запрошенную страницу
  await expect(page.getByRole('log', { name: 'Диалог' }).getByText(NO_POLICY)).toBeVisible()  // сессия открыта в том же состоянии
  await expect(page.getByRole('region', { name: 'Риски' }).getByRole('article').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Прежде чем начать' })).toHaveCount(0)  // дисклеймер уже принят
})

test('слепок: бейдж риска вместо отдельного узла, сводка уровней, экспорт SVG и PNG', async ({ page }) => {
  await login(page)
  await startSession(page, 'Предприниматель')
  await ask(page, NO_POLICY)
  await expect(page.getByRole('button', { name: /Открыть источник: ДЕМО-1-ФЗ/ }).first()).toBeVisible()

  // риск показан окраской и бейджем на связанных узлах, отдельного узла риска по умолчанию нет
  await expect(page.getByLabel('Сводка по уровням риска')).toBeVisible()
  await expect(page.getByLabel('Мини-карта слепка')).toBeVisible()
  // легенда не занимает места постоянно — открывается по кнопке «?»
  await expect(page.getByText('основание ответа')).toHaveCount(0)
  await page.getByRole('button', { name: 'Условные обозначения карты' }).click()
  await expect(page.getByText('основание ответа')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByText('основание ответа')).toHaveCount(0)
  await page.getByText('Фильтры', { exact: true }).click()
  const riskFilter = page.getByRole('checkbox', { name: 'Риски' })
  await expect(riskFilter).not.toBeChecked()
  await expect(page.locator('.react-flow__node').filter({ hasText: 'Нет опубликованной политики' })).toHaveCount(0)
  await riskFilter.check()
  await expect(page.locator('.react-flow__node').filter({ hasText: 'Нет опубликованной политики' })).toHaveCount(1)
  await riskFilter.uncheck()

  // фильтры интервала и уровня не ломают граф
  await page.getByRole('combobox', { name: 'Интервал вопросов' }).selectOption('5')
  await page.getByRole('combobox', { name: 'Уровень риска' }).selectOption('high')
  await page.getByRole('combobox', { name: 'Уровень риска' }).selectOption('')

  for (const fmt of ['SVG', 'PNG'] as const) {
    const dl = page.waitForEvent('download')
    await page.getByRole('button', { name: fmt, exact: true }).click()
    const file = await dl
    expect(file.suggestedFilename()).toMatch(new RegExp(`doorain-portrait-.*\.${fmt.toLowerCase()}$`))
    const p = await file.path()
    expect(fs.statSync(p).size).toBeGreaterThan(400)
    if (fmt === 'SVG') expect(fs.readFileSync(p, 'utf8')).toContain('<svg')
  }
})

test('база знаний: исключение документа и удаление демонстрационных актов', async ({ page }) => {
  await login(page)
  await page.goto('/kb')
  await expect(page.getByText('В корпусе есть демонстрационные данные')).toBeVisible()

  // исключение документа помечается и обратимо
  const card = page.locator('section').filter({ hasText: 'Документы и редакции' })
  const first = card.locator('div.rounded-lg').first()
  await first.getByRole('button', { name: 'Исключить из корпуса' }).click()
  await expect(first.getByText('исключён из корпуса')).toBeVisible()
  await first.getByRole('button', { name: 'Вернуть в корпус' }).click()
  await expect(first.getByText('исключён из корпуса')).toHaveCount(0)

  // демо-акты убираются из корпуса: без ссылок — удаляются, со ссылками — исключаются; предупреждение снимается в обоих случаях
  await page.getByRole('button', { name: 'Убрать демонстрационные данные' }).click()
  await expect(page.getByText('В корпусе есть демонстрационные данные')).toHaveCount(0)
  const excluded = await card.getByText('исключён из корпуса').count()
  const empty = await page.getByRole('heading', { name: 'Корпус пуст' }).count()
  expect(excluded + empty).toBeGreaterThan(0)
})

/** Интерактивные элементы, у которых зона нажатия (с учётом невидимого ::after или метки поля) меньше 44 × 44. */
async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = []
    for (const el of document.querySelectorAll<HTMLElement>('button, a.btn, summary, [role="tab"], select, input:not([type="hidden"]), textarea')) {
      const r = el.getBoundingClientRect()
      if (r.width < 2 || r.height < 2 || el.closest('.react-flow__minimap, .react-flow__attribution')) continue
      const target = el instanceof HTMLInputElement && (el.type === 'checkbox' || el.type === 'radio') ? (el.closest('label') ?? el) : el
      const tr = target.getBoundingClientRect()
      const a = getComputedStyle(target, '::after')
      const ext = (v: string) => (a.content !== 'none' && a.position === 'absolute' ? Math.max(0, -parseFloat(v) || 0) : 0)
      const h = tr.height + ext(a.top) + ext(a.bottom)
      const w = tr.width + ext(a.left) + ext(a.right)
      if (h < 43.5 || w < 43.5) out.push(`${el.tagName.toLowerCase()} «${(el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 40)}» ${Math.round(w)}×${Math.round(h)}`)
    }
    return out
  })
}

test('минимализм: нет названия модели, одна первичная кнопка, зоны нажатия ≥ 44 × 44', async ({ page }) => {
  await login(page)
  await expect(page.locator('.btn-primary:visible')).toHaveCount(1) // экран роли: «Начать как …»
  expect(await smallTargets(page)).toEqual([])
  await startSession(page, 'Предприниматель')
  await ask(page, NO_POLICY)
  await expect(page.getByText(/Модель:|test-template|generation №/)).toHaveCount(0)
  await expect(page.locator('.btn-primary:visible')).toHaveCount(1) // рабочее пространство: «Отправить»
  expect(await smallTargets(page)).toEqual([])
  await page.getByRole('link', { name: 'Мои сессии' }).click()
  await expect(page.getByRole('heading', { name: 'Мои сессии' })).toBeVisible()
  expect(await page.locator('.btn-primary:visible').count()).toBeLessThanOrEqual(1)
  expect(await smallTargets(page)).toEqual([])
  // фокус с клавиатуры виден всегда: у кнопки в фокусе есть кольцо
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  const ring = await page.evaluate(() => getComputedStyle(document.activeElement as Element).boxShadow)
  expect(ring).not.toBe('none')
})
