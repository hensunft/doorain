import type { GraphNode, Level } from '../../lib/api'
import { LEVEL_ORDER, LEVEL_RU, NODE_KIND_RU } from '../../lib/risk'
import { cssVar } from '../../lib/theme'
import { BOX, normParts, short, type Positions } from './graphModel'

/** Экспорт слепка без внешних зависимостей: SVG собирается из тех же координат и форм, что на экране; цвета — фактические
 *  значения токенов текущей темы (в отдельном файле CSS-переменные не работают). PNG — растеризация этого SVG. */
const levelToken = (l: Level | null | undefined) => `--risk-${l === 'medium' ? 'mid' : (l ?? 'none')}`

export function toSvg(nodes: GraphNode[], edges: { source: string; target: string; kind: string }[], pos: Positions, title: string): string {
  const pts = nodes.filter((n) => pos[n.id])
  if (!pts.length) return ''
  const col = {
    bg: cssVar('--surface-2'), ink: cssVar('--ink'), muted: cssVar('--muted'), line: cssVar('--line-strong'), gold: cssVar('--gold'),
    brand: cssVar('--brand'), onBrand: cssVar('--brand-on'), card: cssVar('--surface-alt'), neutral: cssVar('--risk-none-tint'), onRisk: cssVar('--on-risk'), onMid: cssVar('--on-risk-mid'),
  }
  const lv = (l: Level | null | undefined) => cssVar(levelToken(l))
  const pad = 60
  const cx = (n: GraphNode) => pos[n.id]!.x + BOX[n.kind].w / 2
  const cy = (n: GraphNode) => pos[n.id]!.y + BOX[n.kind].h / 2
  const xs = pts.flatMap((n) => [pos[n.id]!.x, pos[n.id]!.x + BOX[n.kind].w])
  const ys = pts.flatMap((n) => [pos[n.id]!.y, pos[n.id]!.y + BOX[n.kind].h])
  const minX = Math.min(...xs) - pad, minY = Math.min(...ys) - pad
  const w = Math.max(...xs) - minX + pad, h = Math.max(...ys) - minY + pad + 46
  const esc = (s: string) => s.replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' })[c] ?? c)
  const byId = new Map(pts.map((n) => [n.id, n]))
  const lines = edges
    .filter((e) => byId.has(e.source) && byId.has(e.target))
    .map((e) => {
      const a = byId.get(e.source)!, b = byId.get(e.target)!
      const dash = e.kind === 'asked_next' ? ' stroke-dasharray="6 4"' : e.kind === 'follow_up_of' ? ' stroke-dasharray="4 4"' : e.kind === 'cites' ? ' stroke-dasharray="1 3"' : ''
      const stroke = e.kind === 'asked_next' ? col.gold : col.line
      return `<line x1="${cx(a) - minX}" y1="${cy(a) - minY}" x2="${cx(b) - minX}" y2="${cy(b) - minY}" stroke="${stroke}" stroke-width="${e.kind === 'asked_next' ? 1.6 : 1}"${dash}/>`
    })
    .join('')
  const shapes = pts
    .map((n) => {
      const x = cx(n) - minX, y = cy(n) - minY
      const fill = n.risk_level ? lv(n.risk_level) : col.neutral
      const edge = n.risk_level ? lv(n.risk_level) : n.resolved_level ? lv(n.resolved_level) : col.line
      const ink = n.risk_level ? (n.risk_level === 'medium' ? col.onMid : col.onRisk) : col.ink
      if (n.kind === 'center') return `<circle cx="${x}" cy="${y}" r="44" fill="${col.brand}" stroke="${col.gold}" stroke-width="4"/><text x="${x}" y="${y + 6}" font-size="20" font-family="Playfair Display, serif" fill="${col.onBrand}" text-anchor="middle">ВЫ</text>`
      if (n.kind === 'topic') return `<rect x="${x - 110}" y="${y - 22}" width="220" height="44" rx="22" fill="${fill}" stroke="${edge}" stroke-width="2"/><text x="${x}" y="${y + 4}" font-size="12" font-weight="600" fill="${ink}" text-anchor="middle">${esc(short(n.label, 32))}</text>`
      if (n.kind === 'question') return `<rect x="${x - 98}" y="${y - 20}" width="196" height="40" rx="10" fill="${col.card}" stroke="${edge}" stroke-width="2"/><text x="${x}" y="${y + 4}" font-size="11" fill="${col.ink}" text-anchor="middle">${esc(short(n.label, 34))}</text>`
      if (n.kind === 'norm') {
        const { act, loc } = normParts(n.label)
        return `<polygon points="${x - 11},${y - 18} ${x + 11},${y - 18} ${x + 21},${y} ${x + 11},${y + 18} ${x - 11},${y + 18} ${x - 21},${y}" fill="${col.card}" stroke="${col.gold}" stroke-width="2"/><text x="${x}" y="${y + 4}" font-size="10" font-family="IBM Plex Mono, monospace" fill="${col.brand}" text-anchor="middle">${esc(act)}</text><text x="${x}" y="${y + 32}" font-size="10" font-family="IBM Plex Mono, monospace" fill="${col.muted}" text-anchor="middle">${esc(short(loc, 16))}</text>`
      }
      return `<rect x="${x - 14}" y="${y - 14}" width="28" height="28" transform="rotate(45 ${x} ${y})" fill="${fill}"/>`
    })
    .join('')
  const legend = LEVEL_ORDER.map((l, i) => `<circle cx="${14 + i * 120}" cy="${h - 16}" r="5" fill="${lv(l)}"/><text x="${24 + i * 120}" y="${h - 12}" font-size="11" fill="${col.muted}">${LEVEL_RU[l]}</text>`).join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${Math.round(w)}" height="${Math.round(h)}" viewBox="0 0 ${Math.round(w)} ${Math.round(h)}" font-family="IBM Plex Sans, system-ui, sans-serif">
<rect width="100%" height="100%" fill="${col.bg}"/><title>${esc(title)}</title>
<text x="14" y="22" font-size="13" font-family="Playfair Display, serif" fill="${col.ink}">${esc(title)}</text>
<text x="14" y="38" font-size="10" fill="${col.muted}">Цвет узла — максимальный активный риск; тонкая обводка — след снятого. Серый не означает «безопасно».</text>
<g transform="translate(0,46)">${lines}${shapes}</g>${legend}</svg>`
}

export function download(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function svgToPng(svg: string, scale = 2): Promise<Blob | null> {
  const m = /width="(\d+)" height="(\d+)"/.exec(svg)
  if (!m) return null
  const w = Number(m[1]) * scale
  const h = Number(m[2]) * scale
  const img = new Image()
  const src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  await new Promise<void>((res, rej) => { img.onload = () => res(); img.onerror = () => rej(new Error('svg')); img.src = src })
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.drawImage(img, 0, 0, w, h)
  return new Promise((res) => canvas.toBlob((b) => res(b), 'image/png'))
}

export const NODE_TITLE = (n: GraphNode): string =>
  `${NODE_KIND_RU[n.kind]}: ${n.label}${n.risk_level ? ` — ${LEVEL_RU[n.risk_level]} риск` : n.resolved_level ? ` — риск снят (был ${LEVEL_RU[n.resolved_level].toLowerCase()})` : ''}${n.risk_count ? `, связанных рисков: ${n.risk_count}` : ''}`

