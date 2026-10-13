/**
 * 全局壳：桌面侧栏玻璃岛 + sticky 顶栏；移动端底部 Dock。
 */
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import {
  LayoutDashboard, MonitorSmartphone, Network, Settings as SettingsIcon,
  Sun, Moon, LogOut, ChevronsLeft, ChevronsRight, Search, Wifi, WifiOff,
} from 'lucide-react'
import { Logo } from '../ui/Logo'
import { BlobField } from './BlobField'
import { useUi } from '../../lib/store'
import { api } from '../../api/client'

const nav = [
  { to: '/', label: '总览', icon: LayoutDashboard, match: ['/'] },
  { to: '/devices', label: '终端', icon: MonitorSmartphone, match: ['/devices'] },
  { to: '/network', label: '网络', icon: Network, match: ['/network'] },
  { to: '/settings', label: '设置', icon: SettingsIcon, match: ['/settings'] },
]

/**
 * 顶栏状态：既看采样器/路由器真实状态，也看 WebSocket 数据新鲜度。
 * 之前只看 WS，未绑定设备时永远显示「连接中断」，容易误判成故障。
 */
type SysState = {
  state: 'unbound' | 'stopped' | 'disconnected' | 'ok'
  router_bound: boolean
  device_name?: string | null
}

function useConnState() {
  const [sys, setSys] = useState<SysState | null>(null)
  const [lastTs, setLastTs] = useState<number>(Date.now())
  const [, force] = useState(0)

  useEffect(() => {
    const load = () => api.get('/system/status').then(r => setSys(r.data)).catch(() => setSys(null))
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const h = () => setLastTs(Date.now())
    window.addEventListener('rp-ws-msg', h)
    const t = setInterval(() => force(x => x + 1), 2000)
    return () => { window.removeEventListener('rp-ws-msg', h); clearInterval(t) }
  }, [])

  const wsFresh = Date.now() - lastTs < 15000
  return { sys, wsFresh }
}

export function ConnIndicator() {
  const { sys, wsFresh } = useConnState()
  const state = sys?.state ?? 'ok'

  const view = (() => {
    if (state === 'unbound') return { text: '未绑定设备', color: 'var(--text-2)', dot: 'off' as const }
    if (state === 'stopped') return { text: '采样未启动', color: 'var(--danger)', dot: 'danger' as const }
    if (state === 'disconnected') return { text: '路由器未连接', color: 'var(--danger)', dot: 'danger' as const }
    return { text: wsFresh ? '实时' : '等待数据', color: wsFresh ? 'var(--text-2)' : 'var(--warn)', dot: wsFresh ? 'on' as const : 'off' as const }
  })()

  const Icon = state === 'ok' && wsFresh ? Wifi : WifiOff
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: view.color }}
      title={sys?.device_name ? `设备：${sys.device_name}` : undefined}>
      <Icon size={13} />
      <span className="hidden sm:inline">{view.text}</span>
      <span className={`status-dot ${view.dot}`} style={{ width: 6, height: 6 }} />
    </span>
  )
}

export default function Layout() {
  const { theme, toggleTheme, sidebarCollapsed, toggleSidebar } = useUi()
  const collapsed = sidebarCollapsed
  const loc = useLocation()
  const goto = useNavigate()
  const [cmdOpen, setCmdOpen] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmdOpen(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const current = nav.find(n => n.match.some(m => (m === '/' ? loc.pathname === '/' : loc.pathname.startsWith(m))))?.label ?? ''

  return (
    <div className="min-h-screen relative">
      <BlobField
        className="fixed inset-0 z-0"
        blobs={[
          { x: 6, y: -2, size: 980, tone: 'violet' },
          { x: 56, y: 34, size: 900, tone: 'blue' },
          { x: 22, y: 20, size: 720, tone: 'cyan' },
          { x: 74, y: -6, size: 780, tone: 'violet' },
        ]}
      />
      <div className="noise" />

      <aside className="glass-l2 fixed z-40 flex flex-col transition-all duration-200"
        style={{ top: 12, left: 12, bottom: 12, width: collapsed ? 72 : 208, borderRadius: 22, padding: '14px 10px' }}>
        <div className="flex items-center gap-2.5 px-2 h-10 shrink-0">
          <span style={{ color: 'var(--signal)' }}><Logo size={24} /></span>
          {!collapsed && (
            <span className="flex flex-col leading-tight">
              <span className="font-bold text-[15px] tracking-tight whitespace-nowrap">RPanel</span>
              <a href="https://github.com/Zhengbf/rpanel" target="_blank" rel="noopener noreferrer"
                className="text-[10px] text-t3 hover:text-t1 transition-colors w-fit">by bf</a>
            </span>
          )}
        </div>
        <nav className="flex flex-col gap-1 mt-5 flex-1" style={{ alignItems: collapsed ? 'center' : 'stretch' }}>
          {nav.map(n => (
            <NavLink key={n.to} to={n.to} title={n.label}
              className={({ isActive }) => {
                const on = isActive || n.match.some(m => m !== '/' && loc.pathname.startsWith(m))
                return `relative flex items-center gap-2.5 rounded-ctrl text-[13px] font-medium transition-colors cursor-pointer ${on ? 'text-t1' : 'text-t2 hover:text-t1 hover:bg-[var(--hover)]'}`
              }}
              style={collapsed ? { padding: '10px 0', justifyContent: 'center' } : { padding: '9px 11px' }}>
              {({ isActive }) => (
                <>
                  {isActive && <span className="absolute left-0 top-1/2 -translate-y-1/2 rounded-full" style={{ width: 3, height: 18, background: 'var(--signal)' }} />}
                  <n.icon size={17} strokeWidth={1.9} style={isActive ? { color: 'var(--signal)' } : undefined} />
                  {!collapsed && <span>{n.label}</span>}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="flex flex-col gap-1 pt-2 border-t border-[var(--border)]" style={{ alignItems: collapsed ? 'center' : 'stretch' }}>
          <button onClick={toggleTheme} aria-label="切换主题"
            className="flex items-center gap-2.5 rounded-ctrl text-[13px] text-t2 hover:text-t1 hover:bg-[var(--hover)] cursor-pointer"
            style={collapsed ? { padding: '10px 0', justifyContent: 'center' } : { padding: '9px 11px' }}>
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            {!collapsed && <span>{theme === 'dark' ? '浅色模式' : '深色模式'}</span>}
          </button>
          <button onClick={() => { localStorage.clear(); goto('/login') }} aria-label="退出登录"
            className="flex items-center gap-2.5 rounded-ctrl text-[13px] text-t2 hover:text-t1 hover:bg-[var(--hover)] cursor-pointer"
            style={collapsed ? { padding: '10px 0', justifyContent: 'center' } : { padding: '9px 11px' }}>
            <LogOut size={16} />
            {!collapsed && <span>退出登录</span>}
          </button>
          <button onClick={toggleSidebar} aria-label="折叠侧栏"
            className="hidden md:flex items-center gap-2.5 rounded-ctrl text-[13px] text-t3 hover:text-t1 hover:bg-[var(--hover)] cursor-pointer"
            style={collapsed ? { padding: '10px 0', justifyContent: 'center' } : { padding: '9px 11px' }}>
            {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
            {!collapsed && <span>收起</span>}
          </button>
        </div>
      </aside>

      <div className="transition-all duration-200" style={{ paddingLeft: collapsed ? 96 : 232, paddingRight: 12 }}>
        <header className="glass-l2 sticky top-3 z-30 flex items-center gap-3 px-4 h-12 mb-4" style={{ borderRadius: 14 }}>
          <span className="text-[14px] font-bold whitespace-nowrap hidden sm:inline">{current}</span>
          <button onClick={() => setCmdOpen(true)}
            className="flex items-center gap-2 flex-1 max-w-96 h-8 px-3 rounded-ctrl border border-[var(--border)] text-t3 text-[12.5px] hover:border-[var(--border-strong)] cursor-pointer">
            <Search size={13} />
            <span className="flex-1 text-left">搜索终端或跳转…</span>
            <kbd className="mono text-[10px] text-t3 border border-[var(--border)] rounded px-1">⌘K</kbd>
          </button>
          <div className="ml-auto flex items-center gap-3"><ConnIndicator /></div>
        </header>
        <main className="page-max px-2 pb-8 relative z-10"><Outlet /></main>
      </div>

      <nav className="glass-l2 fixed z-40 md:hidden flex items-center justify-around"
        style={{ bottom: 12, left: 12, right: 12, height: 58, borderRadius: 18 }}>
        {nav.map(n => (
          <NavLink key={n.to} to={n.to} aria-label={n.label}
            className={({ isActive }) => {
              const on = isActive || n.match.some(m => m !== '/' && loc.pathname.startsWith(m))
              return `flex flex-col items-center gap-0.5 px-3 py-1 rounded-ctrl ${on ? 'text-t1' : 'text-t3'}`
            }}>
            {({ isActive }) => (
              <>
                <n.icon size={19} style={isActive ? { color: 'var(--signal)' } : undefined} />
                <span className="text-[10px]">{n.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {cmdOpen && <CommandPalette onClose={() => setCmdOpen(false)} />}
    </div>
  )
}

function CommandPalette({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState('')
  const [devices, setDevices] = useState<Array<{ ip: string; hostname: string }>>([])
  const nav = useNavigate()
  useEffect(() => {
    api.get('/devices').then(r => setDevices(r.data.map((d: any) => ({ ip: d.ip, hostname: d.hostname || '' })))).catch(() => {})
  }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const pages = [
    { label: '总览', to: '/' }, { label: '终端', to: '/devices' },
    { label: '封禁管理', to: '/blocked' }, { label: '设置', to: '/settings' },
  ]
  const pageHits = pages.filter(p => !q || p.label.includes(q))
  const devHits = q ? devices.filter(d => d.ip.includes(q) || d.hostname.toLowerCase().includes(q.toLowerCase())).slice(0, 6) : []

  const Item = ({ onClick, children }: { onClick: () => void; children: React.ReactNode }) => (
    <button onClick={() => { onClick(); onClose() }}
      className="w-full flex items-center gap-2.5 px-3.5 h-10 rounded-ctrl text-[13px] text-t2 hover:text-t1 hover:bg-[var(--hover)] cursor-pointer text-left">
      {children}
    </button>
  )

  return (
    <div className="fixed inset-0 z-[95] flex items-start justify-center pt-[14vh] p-4" style={{ background: 'rgba(0,0,0,0.4)' }}
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="glass-l2 animate-in w-full max-w-lg overflow-hidden" style={{ borderRadius: 18 }}>
        <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="输入 IP / 主机名，或页面名…"
          className="w-full h-12 px-4 bg-transparent border-b border-[var(--border)] text-[14px] text-t1 placeholder:text-t3 outline-none" />
        <div className="p-1.5 max-h-80 overflow-auto">
          {pageHits.length > 0 && (
            <>
              <div className="px-3.5 pt-2 pb-1 text-[10.5px] uppercase tracking-wider text-t3 mono">页面</div>
              {pageHits.map(p => (
                <Item key={p.to} onClick={() => nav(p.to)}>
                  <LayoutDashboard size={15} /> {p.label}
                </Item>
              ))}
            </>
          )}
          {devHits.length > 0 && (
            <>
              <div className="px-3.5 pt-2 pb-1 text-[10.5px] uppercase tracking-wider text-t3 mono">终端</div>
              {devHits.map(d => (
                <Item key={d.ip} onClick={() => nav(`/devices?ip=${encodeURIComponent(d.ip)}`)}>
                  <MonitorSmartphone size={15} />
                  <span className="mono">{d.ip}</span>
                  <span className="text-t3">{d.hostname || ''}</span>
                </Item>
              ))}
            </>
          )}
          {!pageHits.length && !devHits.length && (
            <div className="px-3.5 py-6 text-center text-t3 text-[12.5px]">无匹配结果</div>
          )}
        </div>
      </div>
    </div>
  )
}
