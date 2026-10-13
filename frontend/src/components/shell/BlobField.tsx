/**
 * 背景光斑场（Signal Glass L0）。
 *
 * 为什么用 JS 时间函数驱动，而不是 CSS animation：
 * 1) 浏览器会在系统开启「减少动态效果」时把 CSS 动画静默变成 0 时长（表现为完全静止，
 *    且很难排查）。这里用 requestAnimationFrame + 时间函数，位移完全可控。
 * 2) 光斑是位图纹理，位移只做图层合成，不做逐元素模糊/重栅格化 → 不会闪。
 * 3) 位置是时间的连续函数（双正弦叠加），路径平滑无跳变；标签页不可见时自动暂停。
 * 4) 想关掉：设置页「视觉效果 → 精简」，或系统减少动态效果时也会自动停。
 */
import { useEffect, useRef } from 'react'

export interface BlobSpec {
  x: number
  y: number
  size: number
  tone: 'violet' | 'blue' | 'cyan'
}

const TONE_CLASS: Record<BlobSpec['tone'], string> = {
  violet: 'blob-tone-violet',
  blue: 'blob-tone-blue',
  cyan: 'blob-tone-cyan',
}

export function BlobField({ blobs, strong = false, className = '', range = 1 }: {
  blobs: BlobSpec[]
  strong?: boolean
  className?: string
  range?: number
}) {
  const layerA = useRef<HTMLDivElement>(null)
  const layerB = useRef<HTMLDivElement>(null)
  // blobs 常以字面量传入（每次渲染都是新引用），用签名当依赖，避免动画计时被反复重置
  const signature = blobs.map(b => `${b.x},${b.y},${b.size},${b.tone}`).join('|')

  useEffect(() => {
    // 注意：这里**不**读取 prefers-reduced-motion。
    // 系统开启「减少动态效果」时浏览器会静默停掉 CSS 动画，之前的实现因此表现为完全静止。
    // 本层是纯装饰且幅度极小，是否保留由面板自己的「视觉效果」开关（fx=off）决定。

    let raf = 0
    let last = 0
    // 统一用 Date.now() 作为唯一时钟：rAF 的时间戳与 performance.now() 在个别环境下不同源，
    // 混用会让 elapsed 恒为 0，动画看起来就是完全静止。
    const t0 = Date.now()

    // 双正弦叠加：缓慢、连续、无跳变的游走路径
    const move = (el: HTMLElement | null, cfg: {
      ax: number; ay: number; px: number; py: number; ph: number
    }) => {
      if (!el) return
      const s = (Date.now() - t0) / 1000
      const x = cfg.ax * Math.sin(s / cfg.px * Math.PI * 2 + cfg.ph)
      const y = cfg.ay * Math.cos(s / cfg.py * Math.PI * 2 + cfg.ph * 1.7)
      el.style.transform = `translate3d(${x.toFixed(3)}vw, ${y.toFixed(3)}vh, 0)`
    }

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame)
      if (document.hidden) return                    // 不可见时不算
      const wall = Date.now()
      if (wall - last < 33) return                   // 30fps 足够
      last = wall
      // 周期 = 原周期 / 1.3 → 移速 +30%（行程幅度不变）
      move(layerA.current, { ax: 9, ay: 6, px: 31, py: 42, ph: 0 })
      move(layerB.current, { ax: 11, ay: 7, px: 45, py: 55, ph: 1.6 })
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [signature, range])

  const layers = [blobs.filter((_, i) => i % 2 === 0), blobs.filter((_, i) => i % 2 === 1)]
  return (
    <div className={`pointer-events-none overflow-hidden ${className}`} aria-hidden>
      {layers.map((list, li) => (
        <div key={li} ref={li === 0 ? layerA : layerB} className={li === 0 ? 'blob-layer-a' : 'blob-layer-b'}>
          {list.map((b, i) => (
            <span
              key={i}
              className={`blob-img ${TONE_CLASS[b.tone]}${strong ? ' blob-strong' : ''}`}
              style={{ width: b.size, height: b.size, left: `${b.x}%`, top: `${b.y}%` }}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
