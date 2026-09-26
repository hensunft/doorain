import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const PASSWORD = 'e2e passphrase 12345'
const NO_POLICY = 'У нас нет политики обработки персональных данных на сайте.'
const SHOTS = path.resolve(__dirname, '../../docs/qa')

async function login(page: Page) {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await page.getByLabel('Логин', { exact: true }).fill('e2e')
  await page.getByLabel('Пароль', { exact: true }).fill(PASSWORD)
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
  await expect(page.getByRole('link', { name: 'Регистрация по приглашению' })).toBeVisible()
  await expect(page.getByRole('contentinfo').getByRole('link', { name: 'Политика обработки персональных данных' })).toBeVisible()  // футер до входа
  await page.getByLabel('Логин', { exact: true }).fill('e2e')
  await page.getByLabel('Пароль', { exact: true }).fill('wrong password 123')
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
  await expect(page.getByText(/Демонстрационные данные|ДЕМО-законы/)).toHaveCount(0)  // синтетика тестового стенда не рекламируется в интерфейсе

  await ask(page, NO_POLICY)
  const chip = page.getByRole('button', { name: /Открыть источник: ДЕМО-1-ФЗ, ст\. 7/ }).first()
  await expect(chip).toBeVisible()
  await expect(page.getByText('Источники и редакции:')).toBeVisible()

  // источник в drawer, возврат фокуса по Escape
  await chip.focus()
  await chip.press('Enter')
  const drawer = page.getByRole('dialog', { name: 'Источник' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText(/Демонстрационные данные/)).toHaveCount(0)
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

test('вход и регистрация: пара «медальон + форма» по центру, форма не сдвигается между маршрутами, без горизонтального скролла', async ({ page }) => {
  fs.mkdirSync(SHOTS, { recursive: true })
  const geo = () => page.evaluate(() => {
    const art = document.querySelector('[data-testid=auth-art]')!.getBoundingClientRect()
    const card = document.querySelector('[data-testid=auth-card]')!.getBoundingClientRect()
    return { vw: innerWidth, sw: document.documentElement.scrollWidth, card: [card.left, card.right], left: art.width ? art.left : card.left }
  })
  // 720 и 1152 — ширина 1440 при масштабе 200 % и 125 %
  for (const w of [375, 720, 768, 1024, 1152, 1280, 1440, 1920]) {
    await page.setViewportSize({ width: w, height: 900 })
    const card: Record<string, number[]> = {}
    for (const route of ['/login', '/register']) {
      await page.goto(route)
      await expect(page.getByTestId('auth-card')).toBeVisible()
      const g = await geo()
      expect(g.sw, `${route} @${w}: горизонтальная прокрутка`).toBeLessThanOrEqual(g.vw)
      expect(Math.abs(g.left - (g.vw - g.card[1]!)), `${route} @${w}: поля слева и справа от композиции`).toBeLessThanOrEqual(1)
      card[route] = g.card
      if (w === 1440 || w === 375) await page.screenshot({ path: path.join(SHOTS, `${route.slice(1)}-${w}.png`), fullPage: true })
    }
    expect(card['/register'], `@${w}: форма сдвигается при переходе «Вход ↔ Регистрация»`).toEqual(card['/login'])
  }
})

test('стекло: без размытия при «уменьшить прозрачность» и принудительных цветах — непрозрачная поверхность', async ({ page }) => {
  await page.goto('/login')
  const card = page.getByTestId('auth-card')
  const style = () => card.evaluate((e) => { const c = getComputedStyle(e); return { filter: c.backdropFilter, bg: c.backgroundColor } })
  expect((await style()).filter).toContain('blur')
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-transparency', value: 'reduce' }] })
  expect(await style()).toEqual({ filter: 'none', bg: expect.stringMatching(/^rgb\(/) })  // rgb без альфы — плотный фон
  await cdp.send('Emulation.setEmulatedMedia', { features: [] })
  await page.emulateMedia({ forcedColors: 'active' })
  expect((await style()).filter).toBe('none')
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
  const code = (await page.locator('code.select-all').first().innerText()).trim()
  await expect(page.locator('code.select-all').nth(1)).toContainText('/register#code=')  // ссылка для регистрации с кодом во фрагменте
  expect(code.length).toBeGreaterThan(20)
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Выйти' }).click()

  const user = `u${Date.now().toString().slice(-8)}`
  await page.goto('/register')
  await page.getByLabel('Код приглашения').fill(code)
  await page.getByLabel('Логин', { exact: true }).fill(user)
  await page.getByLabel('Имя', { exact: true }).fill('Анна')
  await page.getByLabel('Фамилия', { exact: true }).fill('Кузнецова')
  await page.getByLabel('Электронная почта').fill(`${user}@example.com`)
  await page.getByLabel('Пароль', { exact: true }).fill(PASSWORD)
  await page.getByLabel('Повтор пароля').fill('другой пароль 9876')
  await page.getByRole('button', { name: 'Создать учётную запись' }).click()
  await expect(page.getByText('Пароли не совпадают')).toBeVisible()  // проверка на клиенте, запрос не отправлен
  await expect(page.getByText('Нужно ознакомиться с Условиями и Политикой')).toBeVisible()
  await page.getByLabel('Повтор пароля').fill(PASSWORD)
  await page.getByRole('checkbox', { name: /Я ознакомлен/ }).check()
  await page.getByRole('checkbox', { name: /Даю согласие на обработку/ }).check()
  await page.getByRole('button', { name: 'Создать учётную запись' }).click()

  // дисклеймер показывается до работы и фиксируется
  await expect(page.getByRole('heading', { name: 'Прежде чем начать' })).toBeVisible()
  await expect(page.getByText('не оказывает юридических услуг')).toBeVisible()
  await expect(page.getByText('Администратор может просматривать обращения для сопровождения сервиса; такие просмотры фиксируются.')).toBeVisible()
  await expect(page.getByText('Не вводите сведения')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Продолжить' })).toBeDisabled()  // без отметки не пускает
  await page.getByLabel(/Я прочитал/).check()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await expect(page.getByRole('heading', { name: 'Портрет вашего правового положения' })).toBeVisible()
  // имя из профиля видно в интерфейсе; разделы владельца пользователю не видны
  await expect(page.getByRole('link', { name: /Анна Кузнецова/ }).first()).toBeVisible()
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
  await page.getByLabel('Логин', { exact: true }).fill(user)
  await page.getByLabel('Пароль', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page).toHaveURL(url)  // вход возвращает на запрошенную страницу
  await expect(page.getByRole('log', { name: 'Диалог' }).getByText(NO_POLICY)).toBeVisible()  // сессия открыта в том же состоянии
  await expect(page.getByRole('region', { name: 'Риски' }).getByRole('article').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Прежде чем начать' })).toHaveCount(0)  // дисклеймер уже принят

  // изменение профиля видно сразу и переживает повторный вход; логин неизменяем
  await page.goto('/settings')
  await expect(page.getByText(user, { exact: true })).toBeVisible()
  await page.getByLabel('Имя', { exact: true }).fill('Анастасия')
  await page.getByRole('button', { name: 'Сохранить профиль' }).click()
  await expect(page.getByText('Профиль сохранён.')).toBeVisible()
  await expect(page.getByRole('link', { name: /Анастасия Кузнецова/ }).first()).toBeVisible()
  await page.getByLabel('Электронная почта').fill(`new-${user}@example.com`)
  await page.getByLabel('Пароль для смены почты').fill('неверный пароль 000')
  await page.getByRole('button', { name: 'Сохранить профиль' }).click()
  await expect(page.getByRole('alert')).toContainText('текущий пароль')
  await page.getByRole('button', { name: 'Выйти' }).click()
  await page.getByLabel('Логин', { exact: true }).fill(user)
  await page.getByLabel('Пароль', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Войти' }).click()
  await expect(page.getByRole('link', { name: /Анастасия Кузнецова/ }).first()).toBeVisible()
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

test('база знаний: исключение документа обратимо; кнопок и баннеров про «демо» нет', async ({ page }) => {
  await login(page)
  await page.goto('/kb')
  await expect(page.getByRole('heading', { name: 'Документы и редакции' })).toBeVisible()
  await expect(page.getByText(/демонстрационн/i)).toHaveCount(0)

  // исключение документа помечается и обратимо
  const card = page.locator('section').filter({ hasText: 'Документы и редакции' })
  const first = card.locator('div.rounded-lg').first()
  await first.getByRole('button', { name: 'Исключить из корпуса' }).click()
  await expect(first.getByText('исключён из корпуса')).toBeVisible()
  await first.getByRole('button', { name: 'Вернуть в корпус' }).click()
  await expect(first.getByText('исключён из корпуса')).toHaveCount(0)
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

test('разделитель зон: быстрые движения не теряют курсор, после отпускания ширина не меняется, клавиатура и ARIA', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await login(page)
  await startSession(page)
  const sep = page.getByRole('separator', { name: 'Изменить ширину диалога' })
  // боковая панель сворачивается анимацией 150 мс: координаты разделителя берём после её окончания
  await expect.poll(async () => { const a = (await sep.boundingBox())?.x; await page.waitForTimeout(200); return a === (await sep.boundingBox())?.x }).toBe(true)
  const width = () => page.evaluate(() => Math.round(document.querySelector('section[aria-label="Диалог"]')!.getBoundingClientRect().width))
  await expect(sep).toHaveAttribute('aria-valuemin', '260')
  const box = (await sep.boundingBox())!
  const x0 = box.x + box.width / 2
  const y0 = box.y + box.height / 2
  const w0 = await width()
  await page.evaluate(() => { (window as unknown as { __h: Element | null }).__h = document.querySelector('[role=separator]') })
  await page.mouse.move(x0, y0)
  await page.mouse.down()
  for (const dx of [60, 140, 220, 120, -40, -120, 30, 90, 180]) await page.mouse.move(x0 + dx, y0 + 5, { steps: 1 })  // быстрые рывки в обе стороны
  expect(await page.evaluate(() => (window as unknown as { __h: Element | null }).__h === document.querySelector('[role=separator]'))).toBe(true)  // узел не пересоздаётся
  expect(Math.abs((await width()) - (w0 + 180))).toBeLessThanOrEqual(2)  // ширина следует за курсором до последнего рывка
  await page.mouse.move(x0 + 250, y0 + 200, { steps: 1 })
  await page.mouse.up()
  const released = await width()
  await expect(sep).toHaveAttribute('aria-valuenow', String(released))
  for (const dx of [0, 80, -120, 40]) await page.mouse.move(x0 + dx, y0, { steps: 3 })  // кнопка отпущена: движения над разделителем не меняют ширину
  expect(await width()).toBe(released)
  await sep.focus()
  await page.keyboard.press('ArrowLeft')
  expect(await width()).toBe(released - 20)
  await page.keyboard.press('Home')
  expect(await width()).toBe(260)
})

test('закрытие риска: общая фраза не закрывает, описание действия закрывает с пометкой «со слов пользователя»', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await login(page)
  await startSession(page)
  await ask(page, NO_POLICY)
  await page.getByRole('tab', { name: 'План-схема' }).click()
  const step = page.getByRole('checkbox', { name: /Отметить шаг выполненным/ }).first()
  await step.click()
  const field = page.getByLabel('Что именно сделано').first()
  await field.fill('готово')
  await page.getByRole('button', { name: 'Проверить и закрыть' }).first().click()
  await expect(page.getByText('Нужно уточнение:').first()).toBeVisible()
  await expect(page.getByText(/Закрыто 0 из 1/)).toBeVisible()
  await field.fill('Опубликовали политику обработки персональных данных')
  await page.getByRole('button', { name: 'Проверить и закрыть' }).first().click()
  await expect(page.getByText(/Закрыто 1 из 1/)).toBeVisible()
  await expect(page.getByText(/со слов пользователя, независимой проверки нет/).first()).toBeVisible()
})

test('пояснение P и S: наведение — подсказка, клик — окно со шкалой из конфигурации, Escape закрывает', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await login(page)
  await startSession(page)
  await ask(page, NO_POLICY)
  const risks = page.getByRole('region', { name: 'Риски' })
  await risks.getByRole('button', { name: /Нет опубликованной политики/ }).first().click()
  const info = risks.getByRole('button', { name: 'Что означает P' }).first()
  await info.hover()
  await expect(page.getByRole('tooltip')).toContainText('не статистическая вероятность')
  await info.click()
  const dlg = page.getByRole('dialog', { name: 'Что означает P' })
  await expect(dlg).toContainText('Итог P × S')
  await dlg.hover()
  await page.waitForTimeout(400)
  await expect(dlg).toBeVisible()  // курсор в окне — окно не исчезает
  await page.keyboard.press('Escape')
  await expect(dlg).toHaveCount(0)
  await expect(info).toBeFocused()
})

test('тема внизу боковой панели, без редактора цветов в меню; правовые страницы доступны без входа', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await login(page)
  await expect(page.getByRole('link', { name: 'Компоненты' })).toHaveCount(0)
  const nav = page.locator('aside')
  // знак-дверь перекрашивается вместе с темой без перезагрузки и после неё: контраст коробки с фоном ≥ 3:1
  const door = () => page.evaluate(() => {
    const lum = (c: string) => {
      const [r, g, b] = c.match(/[\d.]+/g)!.slice(0, 3).map((v) => { const x = Number(v) / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4 })
      return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
    }
    const token = (v: string) => { const el = document.createElement('i'); el.style.color = `var(${v})`; document.body.append(el); const c = getComputedStyle(el).color; el.remove(); return c }
    const stroke = getComputedStyle(document.querySelector('a[aria-label="DoorAIn — на главную"] svg path')!).stroke
    return Math.min(...['--bg', '--surface'].map((v) => { const [a, b] = [lum(stroke), lum(token(v))].sort((x, y) => y - x); return (a! + 0.05) / (b! + 0.05) }))
  })
  await nav.getByRole('button', { name: 'Тёмная тема' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await door()).toBeGreaterThanOrEqual(3)
  await page.reload()
  await expect(page.getByRole('link', { name: 'DoorAIn — на главную' })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')  // выбор пережил перезагрузку
  expect(await door()).toBeGreaterThanOrEqual(3)
  await nav.getByRole('button', { name: 'Светлая тема' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  expect(await door()).toBeGreaterThanOrEqual(3)
  await nav.getByRole('button', { name: 'Как в системе' }).click()
  for (const colorScheme of ['dark', 'light'] as const) {
    await page.emulateMedia({ colorScheme })
    expect(await door(), `системная тема ${colorScheme}`).toBeGreaterThanOrEqual(3)
  }
  await page.goto('/settings')
  await expect(page.getByRole('group', { name: 'Тема оформления' })).toHaveCount(1)  // один переключатель: в боковой панели
  await page.getByRole('button', { name: 'Выйти' }).click()
  for (const [path_, title] of [['/privacy', 'Политика обработки персональных данных'], ['/terms', 'Условия использования'], ['/contacts', 'Контакты']] as const) {
    await page.goto(path_)
    await expect(page).toHaveURL(new RegExp(path_))
    await expect(page.getByRole('heading', { name: title, level: 1 })).toBeVisible()
    await expect(page.getByText('не заполнено оператором').first()).toBeVisible()  // реквизиты не выдуманы
  }
})

test('карта: неподвижный курсор над узлом — один enter, узлы не прячутся, viewport не прыгает; перетаскивание сдвигает узел', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await login(page)
  await startSession(page)
  await ask(page, NO_POLICY)
  const node = page.locator('.react-flow__node-question').first()
  await expect(node).toBeVisible()
  await page.waitForTimeout(600)  // вписывание карты после первого замера
  // Регрессия 26.09: каждое наведение пересоздавало объекты узлов без measured, React Flow прятал их (visibility: hidden)
  // до повторного замера — курсор «проваливался» на фон, шёл mouseleave, и карта мерцала без движения мыши.
  await page.evaluate(() => {
    const w = window as unknown as { __hov: string[] }
    w.__hov = []
    const flow = document.querySelector('.react-flow')!
    const edge = (e: Event, kind: string) => { const n = (e.target as Element).closest('.react-flow__node'); if (n && !n.contains((e as MouseEvent).relatedTarget as Node)) w.__hov.push(kind) }
    flow.addEventListener('mouseover', (e) => edge(e, 'enter'), true)
    flow.addEventListener('mouseout', (e) => edge(e, 'leave'), true)
    new MutationObserver((ms) => { for (const m of ms) if ((m.target as HTMLElement).style.visibility === 'hidden') w.__hov.push('hidden') })
      .observe(document.querySelector('.react-flow__nodes')!, { attributes: true, subtree: true, attributeFilter: ['style'] })
  })
  const viewport = page.locator('.react-flow__viewport')
  const before = await viewport.getAttribute('style')
  const box = (await node.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await expect(page.locator('.tooltip-card')).toBeVisible()
  await page.waitForTimeout(2000)
  expect(await page.evaluate(() => (window as unknown as { __hov: string[] }).__hov)).toEqual(['enter'])
  await expect(page.locator('.tooltip-card')).toBeVisible()
  expect(await viewport.getAttribute('style')).toBe(before)

  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2 + 40, { steps: 10 })
  await page.mouse.up()
  const moved = (await node.boundingBox())!
  expect(moved.x - box.x).toBeGreaterThan(40)
  expect(await page.evaluate(() => (window as unknown as { __hov: string[] }).__hov)).not.toContain('hidden')
})

test('карта: узлы не залезают друг на друга (и после перетаскивания); связи различимы; весы «Вы» качаются при перемещении и успокаиваются', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await login(page)
  await startSession(page)
  const qs = [NO_POLICY, 'Мы собираем e-mail и телефоны покупателей через форму заказа.', 'Размещаем рекламу у блогеров, нужна ли маркировка?']
  for (const [i, q] of qs.entries()) {
    await ask(page, q)
    await expect(page.locator('.react-flow__node-question')).toHaveCount(i + 1)  // ответ получен, узел на карте
    await expect(page.getByRole('button', { name: 'Отправить' })).toBeVisible()  // генерация завершена (вместо «Стоп»)
  }
  await page.waitForTimeout(800)
  // видимые прямоугольники узлов (с масштабом капсулы темы и подписями) попарно не пересекаются
  const overlaps = () => page.evaluate(() => {
    const rects = [...document.querySelectorAll('.react-flow__node')].filter((n) => getComputedStyle(n).visibility !== 'hidden').map((n) => {
      const parts = [...n.querySelectorAll('.gn > :not(.react-flow__handle)')].map((c) => c.getBoundingClientRect()).filter((r) => r.width && r.height)
      return { id: `${/node-(\w+)/.exec(n.className)?.[1]}:${n.textContent?.slice(0, 16)}@${Math.round(parts[0]?.left ?? 0)},${Math.round(parts[0]?.top ?? 0)}`, l: Math.min(...parts.map((r) => r.left)), t: Math.min(...parts.map((r) => r.top)), r: Math.max(...parts.map((r) => r.right)), b: Math.max(...parts.map((r) => r.bottom)) }
    })
    const bad: string[] = []
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i]!, b = rects[j]!
      if (a.l < b.r - 1 && b.l < a.r - 1 && a.t < b.b - 1 && b.t < a.b - 1) bad.push(`${a.id} × ${b.id}`)
    }
    return bad
  })
  expect(await overlaps()).toEqual([])

  // связи различимы: наведение на вопрос выделяет его ветку (остальное приглушено), на связь — подпись «что → куда»
  await page.locator('.react-flow__node-question').first().hover()
  const opacities = () => page.locator('.react-flow__edge-path').evaluateAll((ps) => ps.map((p) => Number(getComputedStyle(p).opacity)))
  await expect.poll(async () => (await opacities()).filter((o) => o === 1).length).toBeGreaterThan(1)
  expect((await opacities()).filter((o) => o < 0.2).length).toBeGreaterThan(0)
  await page.mouse.move(5, 5)
  const onEdge = await page.evaluate(() => {
    for (const p of document.querySelectorAll<SVGPathElement>('.react-flow__edge-path')) {
      const m = p.getPointAtLength(p.getTotalLength() / 2), r = p.getScreenCTM()!
      const x = m.x * r.a + r.e, y = m.y * r.d + r.f
      if (document.elementFromPoint(x, y)?.closest('.react-flow__edge')) return { x, y }
    }
    return null
  })
  expect(onEdge).not.toBeNull()
  await page.mouse.move(onEdge!.x, onEdge!.y)
  await expect(page.locator('.edge-label')).toBeVisible()
  await page.mouse.move(5, 5)

  const medal = page.locator('.react-flow__node-center .gn-center')
  const pan = () => medal.evaluate((e) => Math.abs(parseFloat(e.style.getPropertyValue('--pan') || '0')))
  const c = (await medal.boundingBox())!
  await page.mouse.move(c.x + c.width / 2, c.y + c.height / 2)
  await page.mouse.down()
  await page.mouse.move(c.x + c.width / 2 + 160, c.y + c.height / 2 - 30, { steps: 12 })
  expect(await pan()).toBeGreaterThan(3)  // чаши отстают от движения
  await page.mouse.up()
  await expect.poll(pan, { timeout: 8000 }).toBe(0)  // колебания затухают
  expect(await overlaps()).toEqual([])

  // вопрос, брошенный поверх темы, остаётся где брошен, а соседи раздвигаются
  const q = (await page.locator('.react-flow__node-question').first().boundingBox())!
  const t = (await page.locator('.react-flow__node-topic').first().boundingBox())!
  await page.mouse.move(q.x + q.width / 2, q.y + q.height / 2)
  await page.mouse.down()
  await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2, { steps: 15 })
  await page.mouse.up()
  await page.waitForTimeout(400)
  expect(await overlaps()).toEqual([])
})

test('нижняя кнопка профиля: «Профиль» целиком, длинное имя — второй строкой; в свёрнутой панели — имя в aria-label и видимая подсказка', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await login(page)
  const { csrf_token } = await (await page.request.get('/api/v1/auth/me')).json()
  const res = await page.request.patch('/api/v1/auth/profile', { headers: { 'X-CSRF-Token': csrf_token, Origin: new URL(page.url()).origin }, data: { first_name: 'Александра-Виктория', last_name: 'Константинопольская-Длинноимённая' } })
  expect(res.ok()).toBeTruthy()
  await page.goto('/history')
  const aside = page.locator('aside')
  const link = aside.getByRole('link', { name: /^Профиль/ })
  const label = link.getByText('Профиль', { exact: true })
  await expect(label).toBeVisible()
  expect(await label.evaluate((e) => e.scrollWidth <= e.clientWidth && e.getBoundingClientRect().width > 40)).toBe(true)  // не «П…»
  const full = 'Александра-Виктория Константинопольская-Длинноимённая'
  await expect(link).toHaveAccessibleName(`Профиль ${full}`)
  await expect(link.getByText(full)).toHaveAttribute('title', full)
  await expect(aside.getByRole('group', { name: 'Тема оформления' })).toBeVisible()  // тема — отдельным рядом, не отнимает ширину
  expect((await aside.getByRole('group', { name: 'Тема оформления' }).boundingBox())!.y).toBeGreaterThan((await link.boundingBox())!.y + 30)

  await aside.getByRole('button', { name: 'Свернуть панель' }).click()
  const compact = aside.getByRole('link', { name: 'Профиль и настройки' })
  await expect(compact).toBeVisible()
  await compact.hover()
  await expect(compact.getByText('Профиль и настройки')).toBeVisible()
  await aside.getByRole('button', { name: 'Развернуть панель' }).click()
})
