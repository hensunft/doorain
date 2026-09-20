import type { Graph, GraphNode, Level } from '../../lib/api'
import { LEVEL_HEX, LEVEL_RU, NODE_KIND_RU } from '../../lib/risk'

export type Positions = Record<string, { x: number; y: number }>

/** Экспорт слепка без внешних зависимостей: SVG собирается из тех же координат, что и на экране, PNG — растеризацией этого SVG. */
export function toSvg(nodes: GraphNode[], edges: Graph['edges'], pos: Positions, size: (n: GraphNode) => number, title: string): string {
  const pts = nodes.filter((n) => pos[n.id])
  if (!pts.length) return ''
  const pad = 60
  const cx = (n: GraphNode) => pos[n.id]!.x + (size(n) + 70) / 2
  const cy = (n: GraphNode) => pos[n.id]!.y + (size(n) + 40) / 2
  const xs = pts.map(cx)
  const ys = pts.map(cy)
  const minX = Math.min(...xs) - pad
  const minY = Math.min(...ys) - pad
  const w = Math.max(...xs) - minX + pad
  const h = Math.max(...ys) - minY + pad + 46
  const esc = (s: string) => s.replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' })[c] ?? c)
  const ids = new Set(pts.map((n) => n.id))
  const lines = edges
    .filter((e) => ids.has(e.source) && ids.has(e.target))
    .map((e) => {
      const a = pts.find((n) => n.id === e.source)!
      const b = pts.find((n) => n.id === e.target)!
      return `<line x1="${cx(a) - minX}" y1="${cy(a) - minY}" x2="${cx(b) - minX}" y2="${cy(b) - minY}" stroke="#d6d6d2" stroke-width="1"${e.kind === 'follow_up_of' ? ' stroke-dasharray="5 4"' : ''}/>`
    })
    .join('')
  const shapes = pts
    .map((n) => {
      const r = size(n) / 2
      const x = cx(n) - minX
      const y = cy(n) - minY
      const fill = n.risk_level ? LEVEL_HEX[n.risk_level] : n.kind === 'center' ? '#2f2e2b' : n.kind === 'topic' ? '#e9e9e7' : '#ffffff'
      const stroke = n.risk_level ? LEVEL_HEX[n.risk_level] : n.resolved_level ? LEVEL_HEX[n.resolved_level] : '#9a9a94'
      const label = esc(n.label.length > 32 ? `${n.label.slice(0, 31)}…` : n.label)
      const body = n.kind === 'question'
        ? `<rect x="${x - r}" y="${y - r}" width="${r * 2}" height="${r * 2}" rx="6" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`
        : n.kind === 'norm'
          ? `<rect x="${x - r}" y="${y - r}" width="${r * 2}" height="${r * 2}" fill="${fill}" stroke="${stroke}" stroke-width="2" transform="rotate(45 ${x} ${y})"/>`
          : `<circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`
      const badge = n.risk_count > 0 ? `<circle cx="${x + r - 2}" cy="${y - r + 2}" r="8" fill="${LEVEL_HEX[n.risk_level ?? 'none']}"/><text x="${x + r - 2}" y="${y - r + 5}" font-size="10" fill="#fff" text-anchor="middle">${n.risk_count}</text>` : ''
      return `${body}${badge}<text x="${x}" y="${y + r + 14}" font-size="11" fill="#2f2e2b" text-anchor="middle">${label}</text>`
    })
    .join('')
  const legend = (['low', 'medium', 'high', 'critical'] as Level[])
    .map((l, i) => `<circle cx="${14 + i * 120}" cy="${h - 16}" r="5" fill="${LEVEL_HEX[l]}"/><text x="${24 + i * 120}" y="${h - 12}" font-size="11" fill="#6b6b66">${LEVEL_RU[l]}</text>`)
    .join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${Math.round(w)}" height="${Math.round(h)}" viewBox="0 0 ${Math.round(w)} ${Math.round(h)}" font-family="Inter, system-ui, sans-serif">
<rect width="100%" height="100%" fill="#fdfdfc"/><title>${esc(title)}</title>
<text x="14" y="22" font-size="13" fill="#2f2e2b">${esc(title)}</text>
<text x="14" y="38" font-size="10" fill="#6b6b66">Цвет узла — максимальный активный риск; тонкая обводка — след снятого. Серый не означает «безопасно».</text>
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
