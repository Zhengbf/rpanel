/** UI 原子组件库：Button/Input/Switch/Segmented/Badge/StatusDot/StatBlock/MeterLED/Skeleton/EmptyState */
import React from 'react'

export function Button({ variant = 'ghost', children, className = '', ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'ghost' | 'primary' | 'danger' }) {
  const base = 'inline-flex items-center justify-center gap-1.5 rounded-ctrl text-[13px] font-medium px-3.5 h-9 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed'
  const styles: Record<string, string> = {
    ghost: 'border border-[var(--border)] bg-transparent text-t2 hover:bg-[var(--hover)] hover:text-t1',
    primary: 'bg-[var(--signal)] text-black font-semibold hover:opacity-90',
    danger: 'bg-[var(--danger)] text-white hover:opacity-90',
  }
  return <button className={`${base} ${styles[variant]} ${className}`} {...rest}>{children}</button>
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`w-full h-9 rounded-ctrl border border-[var(--border)] bg-transparent px-3 text-[13px] text-t1 placeholder:text-t3 outline-none focus:border-[var(--signal)] ${props.className || ''}`} />
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2.5 cursor-pointer">
      <span className="relative inline-block w-9 h-5 rounded-full transition-colors"
        style={{ background: checked ? 'var(--signal)' : 'var(--border-strong)' }}>
        <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all"
          style={{ left: checked ? 18 : 2 }} />
      </span>
      {label && <span className="text-[13px] text-t2">{label}</span>}
    </button>
  )
}

export function Segmented<T extends string>({ options, value, onChange, size }:
  { options: Array<{ value: T; label: string }>; value: T; onChange: (v: T) => void; size?: 'sm' }) {
  return (
    <div className="inline-flex rounded-ctrl border border-[var(--border)] p-0.5 gap-0.5 bg-[var(--hover)]" role="tablist">
      {options.map(o => (
        <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)}
          className={`rounded-[6px] transition-colors cursor-pointer ${size === 'sm' ? 'px-2.5 h-7 text-[12px]' : 'px-3.5 h-8 text-[13px]'} ${value === o.value ? 'bg-[var(--card-solid)] text-t1 font-semibold shadow-sm' : 'text-t2 hover:text-t1'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function StatusDot({ on, danger, label }: { on: boolean; danger?: boolean; label: string }) {
  const cls = danger ? 'danger' : on ? 'on breathe-dot' : 'off'
  const color = danger ? 'var(--danger)' : on ? 'var(--signal)' : 'var(--text-2)'
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`status-dot ${cls}`} />
      <span className="text-[12.5px] font-medium" style={{ color }}>{label}</span>
    </span>
  )
}

export function Badge({ tone, children }: { tone: 'signal' | 'ice' | 'danger' | 'gray'; children: React.ReactNode }) {
  const styles: Record<string, React.CSSProperties> = {
    signal: { background: 'var(--signal-dim)', color: 'var(--signal)' },
    ice: { background: 'var(--ice-dim)', color: 'var(--ice)' },
    danger: { background: 'var(--danger-dim)', color: 'var(--danger)' },
    gray: { background: 'var(--hover)', color: 'var(--text-2)' },
  }
  return <span className="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold" style={styles[tone]}>{children}</span>
}

/** 分段 LED 条（20 格），>80% 转警示色 */
export function MeterLED({ value, max = 100, title }: { value: number; max?: number; title?: string }) {
  const pct = Math.min(100, max > 0 ? (value / max) * 100 : 0)
  const lit = Math.round((pct / 100) * 20)
  const color = pct > 80 ? 'var(--danger)' : pct > 60 ? 'var(--warn)' : 'var(--signal)'
  return (
    <div className="flex items-center gap-[3px]" title={title} role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      {Array.from({ length: 20 }).map((_, i) => (
        <span key={i} className="h-2.5 flex-1 rounded-[1px] transition-colors"
          style={{ background: i < lit ? color : 'var(--border)', opacity: i < lit ? 1 : 0.6 }} />
      ))}
    </div>
  )
}

export function StatBlock({ label, value, sub, tone, spark }: {
  label: string; value: string; sub?: React.ReactNode; tone?: 'signal' | 'ice' | 'danger'; spark?: React.ReactNode
}) {
  const color = tone === 'signal' ? 'var(--signal)' : tone === 'ice' ? 'var(--ice)' : tone === 'danger' ? 'var(--danger)' : 'var(--text)'
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-t3" style={{ fontFamily: 'var(--font-mono)' }}>{label}</div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="mono text-[22px] font-semibold leading-none" style={{ color }}>{value}</span>
        {sub && <span className="text-[12px] text-t3">{sub}</span>}
      </div>
      {spark && <div className="mt-2 h-8">{spark}</div>}
      {!spark && <div className="mt-2 h-px bg-[var(--border)]" />}
    </div>
  )
}

export function Skeleton({ h = 14, w }: { h?: number; w?: number | string }) {
  return <div className="animate-pulse rounded bg-[var(--hover)]" style={{ height: h, width: w ?? '100%' }} />
}

export function EmptyState({ icon, title, desc }: { icon: React.ReactNode; title: string; desc?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-14 gap-2 text-center">
      <div className="text-t3 mb-1">{icon}</div>
      <div className="text-[14px] font-medium text-t1">{title}</div>
      {desc && <div className="text-[12.5px] text-t3 max-w-80">{desc}</div>}
    </div>
  )
}

export function PageHeader({ title, desc, actions }: { title: string; desc?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
      <div>
        <h1 className="text-[20px] font-bold tracking-tight leading-tight">{title}</h1>
        {desc && <div className="text-[12.5px] text-t2 mt-1">{desc}</div>}
      </div>
      {actions && <div className="flex items-center gap-2.5 flex-wrap">{actions}</div>}
    </div>
  )
}

export function Card({ children, className = '', pad = true, ...rest }: React.HTMLAttributes<HTMLDivElement> & { pad?: boolean }) {
  return <div className={`l1 ${pad ? 'p-5' : ''} ${className}`} {...rest}>{children}</div>
}
