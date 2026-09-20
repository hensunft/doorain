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
  await expect(page.getByText('Регистрации нет')).toBeVisible()
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

  // риск в правой панели: уровень дублирован текстом и числом
  const risk = page.getByRole('button', { name: /Нет опубликованной политики обработки ПДн/ }).first()
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
  await page.getByRole('tab', { name: 'Список' }).click()
  await expect(page.getByLabel('Список узлов слепка')).toContainText('Нет опубликованной политики')
  await page.getByRole('tab', { name: 'Хронология' }).click()
  await expect(page.getByLabel('Хронология вопросов')).toContainText(NO_POLICY.slice(0, 20))
  fs.mkdirSync(SHOTS, { recursive: true })
  await page.getByRole('tab', { name: 'Карта' }).click()
  await page.screenshot({ path: path.join(SHOTS, 'workspace-1440.png') })

  expect(violations, 'нарушения CSP или ошибки страницы').toEqual([])
  // перезагрузка: сессия, риск и слепок восстановлены с сервера
  await page.reload()
  await expect(page.getByRole('button', { name: /Нет опубликованной политики обработки ПДн/ }).first()).toBeVisible()
  await expect(page.getByText(NO_POLICY)).toBeVisible()
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
  await page.getByRole('button', { name: 'Экспорт PDF' }).click()
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
      await page.getByRole('tab', { name: 'Диалог' }).click()
    }
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
  await page.getByRole('link', { name: 'История' }).click()
  await expect(page.getByRole('heading', { name: 'История сессий' })).toBeVisible()
  await page.screenshot({ path: path.join(SHOTS, 'history-1440.png') })
  await page.getByRole('link', { name: 'Настройки' }).click()
  await expect(page.getByText('Диагностика системы')).toBeVisible()
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
