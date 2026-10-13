/** 迷你趋势线（无轴无提示，纯视觉）。注意：Hook 必须全部在提前 return 之前。 */
import { useId, useMemo } from 'react'

export function Sparkline({ data, color = 'var(--signal)', height = 32 }:
  { data: Array<[number, number]>; color?: string; height?: number }) {
  const gid = useId().replace(/:/g, '')
  const path = useMemo(() => {
    if (data.length < 2) return null
    const vs = data.map(d => d[1])
    const min = Math.min(...vs), max = Math.max(...vs)
    const range = max - min || 1
    const pts = data.map((d, i) => {
      const x = (i / (data.length - 1)) * 100
      const y = 96 - ((d[1] - min) / range) * 88 - 4
      return x.toFixed(1) + ',' + y.toFixed(1)
    })
    return { line: 'M' + pts.join(' L'), area: 'M0,100 L' + pts.join(' L') + ' L100,100 Z' }
  }, [data])

  if (!path) return <div style={{ height }} />

  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: '100%', height, display: 'block' }} aria-hidden>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={path.area} fill={'url(#' + gid + ')'} />
      <path d={path.line} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
