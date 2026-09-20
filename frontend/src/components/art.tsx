/** Три оригинальные контурные иллюстрации в стиле рисунка тушью: дверь, портретная рамка, карта связей. */
import type { SVGProps } from 'react'

const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' } as const
const pastel = '#f1e3e7'

export function DoorArt(p: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 220 230" role="img" aria-label="Приоткрытая дверь" {...p}>
      <rect x="78" y="40" width="104" height="160" rx="4" fill={pastel} />
      <g {...stroke}>
        <path d="M46 206 C46 150 45 88 47 30 C47 24 51 22 57 21 L128 10 C135 9 138 12 138 18 C138 82 137 150 138 206" />
        <path d="M22 207 C70 205 130 208 196 205" />
        <path d="M138 30 C158 42 166 46 176 52 M138 190 C156 196 168 200 178 206" />
        <path d="M62 44 C61 78 62 110 61 142 M62 44 L118 36 M62 142 L120 138 M118 36 C119 70 118 100 120 138" />
        <circle cx="123" cy="118" r="3.4" />
        <path d="M150 74 C160 66 172 64 184 66 M154 92 C166 86 178 86 190 90 M152 110 C162 106 172 108 182 112" opacity=".55" />
      </g>
    </svg>
  )
}

export function FrameArt(p: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 220 230" role="img" aria-label="Портретная рамка" {...p}>
      <rect x="66" y="52" width="110" height="140" rx="4" fill={pastel} />
      <g {...stroke}>
        <path d="M110 14 L86 44 M110 14 L134 44" />
        <circle cx="110" cy="13" r="2.4" />
        <path d="M52 44 C90 42 128 46 158 44 C159 90 157 140 159 186 C120 188 88 185 52 187 C54 140 51 90 52 44 Z" />
        <path d="M62 54 C92 53 124 55 148 54 C149 92 147 136 148 176 C122 177 92 175 62 177 C63 140 61 92 62 54 Z" />
        <circle cx="105" cy="98" r="17" />
        <path d="M72 174 C74 146 88 132 105 132 C122 132 136 146 138 174" />
        <path d="M96 100 C100 104 110 104 114 100" opacity=".6" />
      </g>
    </svg>
  )
}

export function MapArt(p: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 220 230" role="img" aria-label="Карта связей" {...p}>
      <rect x="76" y="70" width="104" height="104" rx="52" fill={pastel} />
      <g {...stroke}>
        <path d="M110 118 C96 96 82 82 64 70 M110 118 C134 100 152 92 178 88 M110 118 C104 146 100 166 92 184 M110 118 C136 134 154 150 170 172 M64 70 C72 52 84 42 96 36 M178 88 C184 106 186 118 184 134" />
        <circle cx="110" cy="118" r="16" fill="#fff" />
        <circle cx="64" cy="70" r="8" fill="#fff" />
        <circle cx="178" cy="88" r="9" fill="#fff" />
        <circle cx="92" cy="184" r="7" fill="#fff" />
        <circle cx="170" cy="172" r="10" fill="#fff" />
        <circle cx="96" cy="36" r="5" fill="#fff" />
        <circle cx="184" cy="134" r="5" fill="#fff" />
        <path d="M104 118 C108 122 114 122 118 116" opacity=".6" />
      </g>
    </svg>
  )
}
