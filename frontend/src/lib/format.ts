/** 格式化工具（带单元测试，见 lib/format.test.ts） */

/** "2w3d4h19m9s" -> "17天4小时19分钟"：周折算成天，最大单位天，>1天不显示秒 */
export function fmtUptime(raw: string | null | undefined): string {
  if (!raw) return '—'
  const w = raw.match(/(\d+)w/)
  const d = raw.match(/(\d+)d/)
  const h = raw.match(/(\d+)h/)
  const m = raw.match(/(\d+)m/)
  const s = raw.match(/(\d+)s/)
  const days = (w ? +w[1] * 7 : 0) + (d ? +d[1] : 0)
  const parts: string[] = []
  if (days > 0 || w || d) parts.push(days + '天')
  if (h) parts.push(+h[1] + '小时')
  if (m) parts.push(+m[1] + '分钟')
  if (s && days === 0) parts.push(+s[1] + '秒')
  return parts.join('') || raw
}

export function fmtRate(bps: number | null | undefined): string {
  const v = bps ?? 0
  if (v >= 1e9) return (v / 1e9).toFixed(2) + ' GB/s'
  if (v >= 1e6) return (v / 1e6).toFixed(1) + ' MB/s'
  if (v >= 1e3) return (v / 1e3).toFixed(1) + ' KB/s'
  return v.toFixed(0) + ' B/s'
}

export function fmtBytes(b: number | null | undefined): string {
  const v = b ?? 0
  if (v >= 1e12) return (v / 1e12).toFixed(2) + ' TB'
  if (v >= 1e9) return (v / 1e9).toFixed(2) + ' GB'
  if (v >= 1e6) return (v / 1e6).toFixed(1) + ' MB'
  if (v >= 1e3) return (v / 1e3).toFixed(1) + ' KB'
  return v.toFixed(0) + ' B'
}

/** "35m13s"/"never" -> 秒；never/空 -> -1 */
export function parseDuration(raw: string | null | undefined): number {
  if (!raw || raw === 'never') return -1
  let t = 0
  const w = raw.match(/(\d+)w/); if (w) t += +w[1] * 604800
  const d = raw.match(/(\d+)d/); if (d) t += +d[1] * 86400
  const h = raw.match(/(\d+)h/); if (h) t += +h[1] * 3600
  const m = raw.match(/(\d+)m/); if (m) t += +m[1] * 60
  const s = raw.match(/(\d+)s/); if (s) t += +s[1]
  return t
}

export function fmtDuration(sec: number): string {
  if (sec < 0) return '未知'
  if (sec < 60) return sec + '秒'
  if (sec < 3600) return Math.floor(sec / 60) + '分钟'
  if (sec < 86400) return Math.floor(sec / 3600) + '小时' + Math.floor((sec % 3600) / 60) + '分钟'
  return Math.floor(sec / 86400) + '天' + Math.floor((sec % 86400) / 3600) + '小时'
}

export const DASH = '—'
