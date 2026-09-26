import { useId } from 'react'

/** Цифровой слой: созвездие точек и связей в правом верхнем секторе, за весами. fine — только в крупном размере. */
const DOTS: [number, number, number, boolean][] = [
  [124, 36, 1.6, false], [142, 30, 2, false], [158, 42, 1.8, false], [170, 60, 1.6, false], [148, 52, 1.3, true],
  [134, 48, 1.1, true], [178, 82, 1.2, true], [164, 30, 1.1, true], [112, 26, 1.1, true], [182, 102, 1, true],
]
const LINKS: [number, number][] = [[0, 1], [1, 2], [2, 3], [1, 4], [4, 2], [0, 5], [5, 4], [3, 6], [2, 7], [0, 8], [6, 9]]

/** Правый/левый подвес с чашей: две нити от конца коромысла и чаша-полусфера. */
const pan = (x: number) => `M ${x - 20} 113 H ${x + 20} Q ${x + 18} 128 ${x} 129 Q ${x - 18} 128 ${x - 20} 113 Z`

/** Медальон правового положения: бронзовые весы рельефом на тёмном камне, бордовый ореол и цифровой слой.
 *  Символ права, а не портрет и не государственная эмблема. Детализация зависит от размера: в 96–120 px — только
 *  весы и несколько крупных точек, в 320 px — прожилки камня, гравировка и полное созвездие. Цвета — только токены. */
export function Medallion({ size = 96, halo = true, className = '', title }: { size?: number; halo?: boolean; className?: string; title?: string }) {
  const id = useId().replace(/:/g, '')
  const u = (x: string) => `url(#${id}-${x})`
  const fine = size >= 200
  const thread = fine ? 1.2 : 2.2
  return (
    <svg width={size} height={size} viewBox="0 0 200 200" className={className} role={title ? 'img' : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <defs>
        <radialGradient id={`${id}-stone`} cx="36%" cy="28%" r="80%">
          <stop offset="0%" style={{ stopColor: 'var(--marble-hi)' }} />
          <stop offset="100%" style={{ stopColor: 'var(--marble-lo)' }} />
        </radialGradient>
        <linearGradient id={`${id}-metal`} x1="0" y1="0" x2="0.35" y2="1">
          <stop offset="0%" style={{ stopColor: 'var(--marble-relief)' }} />
          <stop offset="45%" style={{ stopColor: 'var(--gold)' }} />
          <stop offset="100%" style={{ stopColor: 'var(--marble-metal)' }} />
        </linearGradient>
        <linearGradient id={`${id}-rim`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" style={{ stopColor: 'var(--gold)', stopOpacity: 0.9 }} />
          <stop offset="55%" style={{ stopColor: 'var(--gold)', stopOpacity: 0.15 }} />
          <stop offset="100%" style={{ stopColor: 'var(--gold)', stopOpacity: 0.5 }} />
        </linearGradient>
        <radialGradient id={`${id}-sheen`} cx="30%" cy="18%" r="55%">
          <stop offset="0%" style={{ stopColor: 'var(--marble-relief)', stopOpacity: 0.2 }} />
          <stop offset="100%" style={{ stopColor: 'var(--marble-relief)', stopOpacity: 0 }} />
        </radialGradient>
        <clipPath id={`${id}-disc`}><circle cx="100" cy="100" r="84" /></clipPath>
        {fine && (
          /* Прожилки камня: шум → только альфа → цвет прожилки */
          <filter id={`${id}-veins`} x="0" y="0" width="100%" height="100%">
            <feTurbulence type="turbulence" baseFrequency="0.008 0.03" numOctaves="3" seed="11" result="n" />
            <feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -2.4 0 0 0 1.1" result="a0" />
            <feComponentTransfer in="a0" result="a"><feFuncA type="gamma" amplitude="1" exponent="3" offset="0" /></feComponentTransfer>
            <feFlood style={{ floodColor: 'var(--marble-vein)' }} result="f" />
            <feComposite in="f" in2="a" operator="in" />
          </filter>
        )}
        {/* Рельеф: весы выступают из камня — тень вниз-вправо, блик слева сверху */}
        <filter id={`${id}-relief`} x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="1.6" result="b" />
          <feOffset in="b" dx="1.6" dy="2.4" result="o" />
          <feFlood style={{ floodColor: 'var(--marble-lo)' }} floodOpacity="0.85" result="c" />
          <feComposite in="c" in2="o" operator="in" result="sh" />
          <feSpecularLighting in="b" surfaceScale="3" specularConstant="0.7" specularExponent="18" result="s" style={{ lightingColor: 'var(--marble-relief)' }}>
            <feDistantLight azimuth="235" elevation="42" />
          </feSpecularLighting>
          <feComposite in="s" in2="SourceAlpha" operator="in" result="si" />
          <feMerge><feMergeNode in="sh" /><feMergeNode in="SourceGraphic" /><feMergeNode in="si" /></feMerge>
        </filter>
      </defs>

      {halo && <circle cx="100" cy="100" r="97" fill="none" style={{ stroke: 'var(--brand-line)' }} strokeOpacity="0.45" strokeWidth="1" />}
      {halo && <circle cx="100" cy="100" r="91" fill="none" style={{ stroke: 'var(--brand-glow)' }} strokeWidth="4" />}
      <circle cx="100" cy="100" r="85" fill={u('stone')} />
      <g clipPath={u('disc')}>
        {fine && <rect x="0" y="0" width="200" height="200" filter={u('veins')} opacity="0.3" />}
        {fine && <circle cx="100" cy="100" r="76" fill="none" style={{ stroke: 'var(--gold)' }} strokeOpacity="0.22" strokeWidth="0.6" />}

        <g fill="none" style={{ stroke: 'var(--gold)' }} strokeWidth={fine ? 0.6 : 1.1} strokeOpacity="0.45">
          {LINKS.filter(([a, b]) => fine || (!DOTS[a]![3] && !DOTS[b]![3])).map(([a, b]) => {
            const p = DOTS[a]!, q = DOTS[b]!
            return <line key={`${a}-${b}`} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} />
          })}
        </g>
        <g style={{ fill: 'var(--gold)' }}>
          {DOTS.filter((d) => fine || !d[3]).map(([x, y, r]) => <circle key={`${x}-${y}`} cx={x} cy={y} r={fine ? r : r * 1.7} opacity={Math.max(0.35, 1.1 - (x - 110) / 90)} />)}
        </g>

        {/* Весы: навершие, коромысло с осью, стойка, ступенчатое основание, две нити и чаша с каждой стороны */}
        <g filter={u('relief')} fill={u('metal')}>
          <circle cx="100" cy="50" r="4.5" />
          <path d="M 44 65 L 100 61.5 L 156 65 L 156 69 L 100 71 L 44 69 Z" />
          <circle cx="46" cy="67" r="3.4" />
          <circle cx="154" cy="67" r="3.4" />
          <circle cx="100" cy="66" r="6.5" />
          <path d="M 97 70 H 103 L 104.5 146 H 95.5 Z" />
          <path d="M 90 146 H 110 L 112.5 151 H 87.5 Z" />
          <path d="M 80 151 H 120 L 125 159 H 75 Z" />
          <path d={pan(46)} />
          <path d={pan(154)} />
        </g>
        <g fill="none" style={{ stroke: 'var(--gold)' }} strokeWidth={thread} strokeLinecap="round">
          <path d="M 46 69 L 27.5 113 M 46 69 L 64.5 113" />
          <path d="M 154 69 L 135.5 113 M 154 69 L 172.5 113" />
        </g>
        {fine && (
          <g fill="none" style={{ stroke: 'var(--marble-lo)' }} strokeOpacity="0.55" strokeWidth="0.8" strokeLinecap="round">
            {/* гравировка: осевая линия коромысла, кромки чаш, ось и ступени основания */}
            <path d="M 50 66.8 L 100 64.5 L 150 66.8" />
            <path d="M 27 113 H 65 M 135 113 H 173" />
            <circle cx="100" cy="66" r="2.6" />
            <path d="M 92 151 H 108 M 80 159 H 120" />
          </g>
        )}
        <circle cx="100" cy="100" r="85" fill={u('sheen')} />
      </g>
      <circle cx="100" cy="100" r="84.5" fill="none" stroke={u('rim')} strokeWidth="1.6" />
    </svg>
  )
}
