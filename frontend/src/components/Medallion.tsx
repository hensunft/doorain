import { useId } from 'react'

/** Узлы «цифрового слоя»: профиль переходит в точки и связи к правому краю медальона (ближе к лицу — ярче). */
const DOTS: [number, number, number][] = [
  [152, 84, 1.8], [160, 96, 2.2], [158, 112, 1.8], [166, 124, 2], [156, 136, 1.6], [150, 150, 1.6], [172, 106, 1.5], [170, 86, 1.4],
  [178, 120, 1.2], [174, 140, 1.2], [163, 158, 1.1], [147, 70, 1.4], [158, 62, 1.1], [182, 98, 0.9], [184, 132, 0.9], [168, 72, 1],
]
const LINKS: [number, number][] = [[11, 0], [0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [1, 6], [6, 3], [0, 7], [7, 6], [6, 8], [3, 9], [5, 10], [11, 12], [12, 15], [15, 7], [8, 13], [9, 14]]
/** Стеклянные грани поверх лица: профиль «оцифровывается» геометрией. */
const FACETS = ['139.5,89 152,84 144.5,102', '144.5,102 152,84 160,96', '144.5,102 160,96 158,112', '149.5,115.5 158,112 144.5,102', '141.2,130.5 156,136 147.5,118.5']

/** Медальон правовой личности: тёмный мрамор с рельефным классическим профилем, стеклянный ореол и частицы данных.
 *  Не изображает конкретного человека — это абстрактный образ пользователя. Цвета только из токенов (--marble-*, --gold). */
export function Medallion({ size = 96, halo = true, className = '', title }: { size?: number; halo?: boolean; className?: string; title?: string }) {
  const id = useId().replace(/:/g, '')
  const u = (x: string) => `url(#${id}-${x})`
  return (
    <svg width={size} height={size} viewBox="0 0 200 200" className={className} role={title ? 'img' : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <defs>
        <radialGradient id={`${id}-stone`} cx="36%" cy="28%" r="80%">
          <stop offset="0%" style={{ stopColor: 'var(--marble-hi)' }} />
          <stop offset="100%" style={{ stopColor: 'var(--marble-lo)' }} />
        </radialGradient>
        <linearGradient id={`${id}-bust`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" style={{ stopColor: 'var(--marble-hi)' }} />
          <stop offset="100%" style={{ stopColor: 'var(--marble-lo)' }} />
        </linearGradient>
        <linearGradient id={`${id}-rim`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" style={{ stopColor: 'var(--gold)', stopOpacity: 0.9 }} />
          <stop offset="55%" style={{ stopColor: 'var(--gold)', stopOpacity: 0.15 }} />
          <stop offset="100%" style={{ stopColor: 'var(--gold)', stopOpacity: 0.5 }} />
        </linearGradient>
        <radialGradient id={`${id}-sheen`} cx="30%" cy="18%" r="55%">
          <stop offset="0%" style={{ stopColor: 'var(--marble-relief)', stopOpacity: 0.22 }} />
          <stop offset="100%" style={{ stopColor: 'var(--marble-relief)', stopOpacity: 0 }} />
        </radialGradient>
        <clipPath id={`${id}-disc`}><circle cx="100" cy="100" r="84" /></clipPath>
        {/* Прожилки мрамора: шум → только альфа → цвет прожилки */}
        <filter id={`${id}-veins`} x="0" y="0" width="100%" height="100%">
          <feTurbulence type="turbulence" baseFrequency="0.008 0.03" numOctaves="3" seed="11" result="n" />
          <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -2.4 0 0 0 1.1" result="a0" />
          <feComponentTransfer in="a0" result="a"><feFuncA type="gamma" amplitude="1" exponent="3" offset="0" /></feComponentTransfer>
          <feFlood style={{ floodColor: 'var(--marble-vein)' }} result="f" />
          <feComposite in="f" in2="a" operator="in" />
        </filter>
        {/* Рельеф профиля: свет слева сверху, как в музейной витрине */}
        <filter id={`${id}-relief`} x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="2.4" result="b" />
          <feDiffuseLighting in="b" surfaceScale="3.5" diffuseConstant="1.05" result="d" style={{ lightingColor: 'var(--marble-relief)' }}>
            <feDistantLight azimuth="235" elevation="48" />
          </feDiffuseLighting>
          <feComposite in="d" in2="SourceAlpha" operator="in" result="di" />
          <feBlend in="SourceGraphic" in2="di" mode="multiply" result="m" />
          <feSpecularLighting in="b" surfaceScale="4" specularConstant="0.8" specularExponent="22" result="s" style={{ lightingColor: 'var(--marble-relief)' }}>
            <feDistantLight azimuth="235" elevation="38" />
          </feSpecularLighting>
          <feComposite in="s" in2="SourceAlpha" operator="in" result="si" />
          <feComposite in="si" in2="m" operator="arithmetic" k2="0.7" k3="1" />
        </filter>
      </defs>

      {halo && <circle cx="100" cy="100" r="97" fill="none" style={{ stroke: 'var(--gold)' }} strokeOpacity="0.28" strokeWidth="0.8" />}
      {halo && <circle cx="100" cy="100" r="91" fill="none" style={{ stroke: 'var(--marble-relief)' }} strokeOpacity="0.08" strokeWidth="5" />}
      <circle cx="100" cy="100" r="85" fill={u('stone')} />
      <g clipPath={u('disc')}>
        <rect x="0" y="0" width="200" height="200" filter={u('veins')} opacity="0.35" />
        <path
          filter={u('relief')}
          fill={u('bust')}
          d="M 114 194 C 113.5 190.7 111.2 179.5 111 174 C 110.8 168.5 111.3 164.2 113 161 C 114.7 157.8 118 156.3 121 155 C 124 153.7 128.3 154 131 153 C 133.7 152 135.6 150.8 137 149 C 138.4 147.2 139.3 144.4 139.5 142.5 C 139.7 140.6 137.8 138.9 138 137.5 C 138.2 136.1 140 135.2 140.5 134 C 141 132.8 141.2 131.4 141.2 130.5 C 141.1 129.6 140.1 129.5 140.2 128.8 C 140.3 128.1 141.8 127.3 142 126.2 C 142.2 125.1 141.2 123.1 141.4 122 C 141.6 120.9 142 120.4 143 119.8 C 144 119.2 146.4 119.2 147.5 118.5 C 148.6 117.8 150 118.2 149.5 115.5 C 149 112.8 146.2 106.4 144.5 102 C 142.8 97.6 140.3 92.3 139.5 89 C 138.7 85.7 139.8 84.8 139.5 82 C 139.2 79.2 138.5 75.3 137.5 72 C 136.5 68.7 134.2 63.7 133.5 62 Q 133.9 54.2 128 52 Q 125.4 44.8 118 44.5 Q 113 38.3 105 40 Q 98.5 35.8 91 40 Q 83.9 37.8 78 44 Q 70.3 44.2 66 52 Q 58.4 54.9 56.5 64 Q 49.8 69 50.5 78 Q 44.9 84.3 47.5 92 C 38 94 34 110 42 120 C 48 128 58 128 62 126 C 62.7 128.3 64.9 134.3 66 140 C 67.1 145.7 68.5 151 68.5 160 C 68.5 169 66.4 188.3 66 194 Z"
        />
        <g fill="none" style={{ stroke: 'var(--marble-lo)' }} strokeOpacity="0.6" strokeWidth="1" strokeLinecap="round">
          {/* резьба камеи: граница волос, пряди, ухо, веко, бровь, узел волос, мышца шеи */}
          <path d="M 133.5 62 C 124 66 116 74 110 84 C 104 94 98 104 94 116 C 90 126 82 132 72 134" strokeOpacity="0.75" />
          <path d="M 126 50 C 112 54 98 60 86 72 C 78 80 70 92 64 104" />
          <path d="M 116 45 C 100 50 84 58 72 72 C 64 82 58 94 54 108" />
          <path d="M 128 60 C 116 66 104 76 96 90 C 90 100 84 110 76 120" />
          <path d="M 99 95 C 94 95 92.5 103 95 108 C 96.5 111 99.5 110.5 100 108" />
          <path d="M 122 93.5 Q 127 90.5 132 93.5" />
          <path d="M 119 86.5 Q 128 83 137 86.5" strokeOpacity="0.4" />
          <path d="M 44 106 C 41 98 49 92 55 96 C 60 100 55 108 49 106" />
          <path d="M 104 156 C 100 166 98 178 98 192" strokeOpacity="0.35" />
          <path d="M 131 150 C 118 146 106 140 100 128" strokeOpacity="0.25" />
        </g>
        <g fill="none" style={{ stroke: 'var(--gold)' }} strokeWidth="0.6" strokeOpacity="0.4">
          {FACETS.map((p) => <polygon key={p} points={p} />)}
          {LINKS.map(([a, b]) => { const p = DOTS[a]!, q = DOTS[b]!; return <line key={`${a}-${b}`} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} /> })}
        </g>
        <g style={{ fill: 'var(--gold)' }}>
          {DOTS.map(([x, y, r]) => <circle key={`${x}-${y}`} cx={x} cy={y} r={r} opacity={Math.max(0.3, 1.15 - (x - 145) / 45)} />)}
        </g>
        <circle cx="100" cy="100" r="85" fill={u('sheen')} />
      </g>
      <circle cx="100" cy="100" r="84.5" fill="none" stroke={u('rim')} strokeWidth="1.6" />
    </svg>
  )
}
