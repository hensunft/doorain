// Приёмка A8: цвета только из tokens.css, никаких внешних доменов в клиенте (шрифты и скрипты — локальные).
const sources = import.meta.glob(['/src/**/*.{ts,tsx,css}', '/index.html', '!/src/**/*.test.*', '!/src/lib/api-types.ts'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

const COLOR = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch)\(/g
const URL_RE = /https?:\/\/[^\s'"`)]+/g
const ALLOWED_URLS = ['http://www.w3.org/2000/svg'] // пространство имён SVG, не сетевой запрос

describe('приёмка оформления', () => {
  it('исходники найдены', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20)
    expect(sources['/index.html']).toBeDefined()
  })

  it('литеральные цвета — только в tokens.css', () => {
    const bad = Object.entries(sources)
      .filter(([f]) => !f.endsWith('/styles/tokens.css'))
      .flatMap(([f, text]) => (text.match(COLOR) ?? []).map((m) => `${f}: ${m}`))
    expect(bad).toEqual([])
  })

  it('нет обращений к внешним доменам', () => {
    const bad = Object.entries(sources).flatMap(([f, text]) => (text.match(URL_RE) ?? []).filter((u) => !ALLOWED_URLS.includes(u)).map((u) => `${f}: ${u}`))
    expect(bad).toEqual([])
    expect(sources['/src/styles/index.css']).not.toMatch(/@import\s+url\(\s*['"]?https?:/)
  })
})
