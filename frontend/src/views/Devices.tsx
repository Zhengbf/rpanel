/**
 * 设备列表（终端 → 设备列表）
 *
 * 列宽：默认按最长内容计算（IP 支持 192.168.111.111 这类三位数全显示），
 * 并且每列可拖拽调整宽度，宽度存 localStorage，刷新后保持。
 * 新增列只需在 COLS 里加一项，并在这里补对应的单元格渲染。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Search, ArrowUpDown, ArrowUp, ArrowDown, X, Pencil, RotateCcw } from 'lucide-react'
import api from '../api/client'
import { useWebSocket } from '../ws/useWebSocket'
import AlertBar from '../components/AlertBar'
import { Segmented } from '../components/ui'
import { ConfirmModal } from '../components/ui/Modal'
import { fmtRate, fmtBytes, parseDuration } from '../lib/format'

type SortKey = 'ip' | 'hostname' | 'note' | 'conn_count' | 'rx_rate' | 'tx_rate' | 'total_bytes' | 'last_seen'
type SortDir = 'asc' | 'desc'

/** 列定义：w = 默认宽度，min = 拖拽下限，flex = 自动占满剩余空间（不可拖拽） */
const COLS = [
  { key: 'status', label: '状态', w: 88, min: 78, sort: null },
  { key: 'ip', label: 'IP 地址', w: 158, min: 132, sort: 'ip' },
  { key: 'rx_rate', label: '↓ 下载', w: 110, min: 92, sort: 'rx_rate', num: true },
  { key: 'tx_rate', label: '↑ 上传', w: 110, min: 92, sort: 'tx_rate', num: true },
  { key: 'conn_count', label: '会话', w: 60, min: 52, sort: 'conn_count', num: true },
  { key: 'last_seen', label: '在线时长', w: 106, min: 92, sort: 'last_seen', num: true },
  { key: 'hostname', label: '主机名', w: 152, min: 110, sort: 'hostname' },
  { key: 'total_bytes', label: '累计流量', w: 100, min: 86, sort: 'total_bytes', num: true },
  { key: 'note', label: '备注', w: 140, min: 110, sort: 'note', flex: true },
  { key: 'blocked', label: '封禁', w: 86, min: 74, sort: null },
  { key: 'actions', label: '操作', w: 100, min: 88, sort: null },
] as const

type ColKey = typeof COLS[number]['key']
const STORAGE_KEY = 'rp-device-colw'

function loadWidths(): Record<string, number> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return typeof parsed === 'object' && parsed ? parsed : {}
  } catch {
    return {}
  }
}

export default function Devices() {
  const [devices, setDevices] = useState<any[]>([])
  const [search, setSearch] = useState('')
  const [detail, setDetail] = useState<any>(null)
  const [confirmBlock, setConfirmBlock] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<'all' | 'online' | 'offline' | 'blocked'>('all')
  const [editingNote, setEditingNote] = useState<{ ip: string; value: string } | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('ip')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [widths, setWidths] = useState<Record<string, number>>(loadWidths)
  const dragging = useRef<{ key: ColKey; startX: number; startW: number } | null>(null)
  const tableRef = useRef<HTMLTableElement>(null)

  const colWidth = (c: typeof COLS[number]) => widths[c.key] ?? c.w

  // ---- 拖拽调整列宽 ----
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const d = dragging.current
      if (!d) return
      const col = COLS.find(c => c.key === d.key)!
      const next = Math.max(col.min, Math.round(d.startW + (e.clientX - d.startX)))
      setWidths(w => ({ ...w, [d.key]: next }))
    }
    const onUp = () => {
      if (dragging.current) {
        dragging.current = null
        document.body.style.userSelect = ''
        setWidths(w => {
          try { localStorage.setItem(STORAGE_KEY, JSON.stringify(w)) } catch {}
          return w
        })
      }
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [])

  const startDrag = (e: React.PointerEvent, key: ColKey) => {
    const col = COLS.find(c => c.key === key)!
    dragging.current = { key, startX: e.clientX, startW: colWidth(col) }
    document.body.style.userSelect = 'none'
    e.preventDefault()
  }

  const resetWidths = () => {
    setWidths({})
    try { localStorage.removeItem(STORAGE_KEY) } catch {}
  }

  // ---- 数据 ----
  const load = () => api.get('/devices').then(r => { setDevices(r.data); setLoading(false) }).catch(() => setLoading(false))
  useEffect(() => { load() }, [])

  useWebSocket(['devices'], (_t, data) => {
    setDevices(prev => prev.map(d => {
      const u = data.devices.find((x: any) => x.ip === d.ip)
      return u ? { ...d, rx_rate: u.rx_rate, tx_rate: u.tx_rate,
                   conn_count: u.conn_count, total_bytes: u.total_bytes } : d
    }))
  })

  const saveNote = async () => {
    if (!editingNote) return
    await api.put('/devices/note', { ip: editingNote.ip, note: editingNote.value }).catch(() => {})
    setEditingNote(null)
    load()
  }

  const doBlock = async (ip: string) => {
    try { await api.post('/firewall/block', { ip, reason: 'UI 手动封禁' }) } catch {}
    setConfirmBlock(null)
    load()
  }
  const doUnblock = async (ip: string) => {
    await api.post('/firewall/unblock', { ip })
    load()
  }
  const openDetail = async (ip: string) => {
    const { data } = await api.get(`/sessions/${ip}`)
    setDetail(data)
  }

  const shown = useMemo(() => {
    const filtered = devices.filter(d => {
      const hit = !search || d.ip.includes(search) || (d.hostname || '').toLowerCase().includes(search.toLowerCase())
      const st = statusFilter === 'all' ? true : statusFilter === 'online' ? d.online : statusFilter === 'offline' ? !d.online : d.blocked
      return hit && st
    })
    const dir = sortDir === 'asc' ? 1 : -1
    const ipNum = (ip: string) => {
      const p = (ip || '').split('.').map(Number)
      return p.length === 4 && p.every(n => !isNaN(n)) ? ((p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]) >>> 0 : -1
    }
    return [...filtered].sort((a, b) => {
      if (a.online !== b.online) return a.online ? -1 : 1
      let va: any, vb: any
      if (sortKey === 'ip') { va = ipNum(a.ip); vb = ipNum(b.ip) }
      else if (sortKey === 'last_seen') { va = parseDuration(a.last_seen); vb = parseDuration(b.last_seen) }
      else if (['conn_count', 'rx_rate', 'tx_rate', 'total_bytes'].includes(sortKey)) { va = a[sortKey] ?? 0; vb = b[sortKey] ?? 0 }
      else { va = (a[sortKey] ?? '').toString().toLowerCase(); vb = (b[sortKey] ?? '').toString().toLowerCase() }
      if (va < vb) return -1 * dir
      if (va > vb) return 1 * dir
      return ipNum(a.ip) - ipNum(b.ip)
    })
  }, [devices, search, statusFilter, sortKey, sortDir])

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(k); setSortDir('asc') }
  }

  const SortIcon = ({ k }: { k: SortKey | null }) => {
    if (!k) return null
    if (k !== sortKey) return <ArrowUpDown size={11} className="sort-ind" style={{ opacity: 0.3 }} />
    return sortDir === 'asc'
      ? <ArrowUp size={11} className="sort-ind text-signal" />
      : <ArrowDown size={11} className="sort-ind text-signal" />
  }

  return (
    <div>
      <AlertBar />

      <div className="page-head">
        <div>
          <div className="page-title">终端</div>
          <div className="page-desc">共 {devices.length} 台 · 在线 {devices.filter(d => d.online).length} 台</div>
        </div>
        <div className="flex items-center gap-2.5 flex-wrap">
          <Segmented size="sm" value={statusFilter} onChange={setStatusFilter} options={[
            { value: 'all', label: '全部' }, { value: 'online', label: '在线' },
            { value: 'offline', label: '离线' }, { value: 'blocked', label: '已封禁' }]} />
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-t3" />
            <input className="input pl-9 w-56" placeholder="搜索 IP / 主机名" value={search}
              onChange={e => setSearch(e.target.value)} />
          </div>
          <button className="btn" onClick={resetWidths} title="恢复默认列宽">
            <RotateCcw size={13} /> 列宽
          </button>
        </div>
      </div>

      <div className="table-wrap">
        <table className="data-table col-fixed" ref={tableRef}>
          <colgroup>
            {COLS.map(c => (
              <col key={c.key} style={{ width: (c as any).flex ? undefined : colWidth(c) }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {COLS.map(c => (
                <th key={c.key}
                  className={`${c.sort ? 'sortable' : ''}${(c as any).num ? ' th-num' : ''}`}
                  onClick={c.sort ? () => toggleSort(c.sort as SortKey) : undefined}>
                  {c.label}
                  <SortIcon k={c.sort as SortKey | null} />
                  {!(c as any).flex && (
                    <span
                      className="col-resizer"
                      onPointerDown={e => startDrag(e, c.key)}
                      onClick={e => e.stopPropagation()}
                      title="拖动调整列宽"
                    />
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i}>{COLS.map((c, j) => (
                  <td key={c.key}><div className="skeleton" style={{ height: 14, width: j === 0 ? 24 : '70%' }} /></td>
                ))}</tr>
              ))
            ) : shown.map(d => (
              <tr key={d.ip} style={{ opacity: d.online ? 1 : 0.55 }}>
                <td className="status-cell">
                  <span className={`pill ${d.online ? 'pill-on' : 'pill-off'}`}>
                    <span className={`status-dot ${d.online ? 'on' : 'off'}`} style={{ width: 6, height: 6 }} />
                    {d.online ? '在线' : '离线'}
                  </span>
                </td>
                <td className="mono" style={{ fontWeight: 500 }}>{d.ip}</td>
                <td className={`num ${d.rx_rate >= 1024 ? 'text-signal' : 'dim-0'}`}>{fmtRate(d.rx_rate)}</td>
                <td className={`num ${d.tx_rate >= 1024 ? 'text-ice' : 'dim-0'}`}>{fmtRate(d.tx_rate)}</td>
                <td className="num text-2">{d.conn_count}</td>
                <td className="num mono text-2">{d.last_seen || '—'}</td>
                <td style={{ fontWeight: 500 }} title={d.hostname || ''}>{d.hostname || '—'}</td>
                <td className="num text-2">{fmtBytes(d.total_bytes)}</td>
                <td className="text-2 wrap-cell">
                  {editingNote?.ip === d.ip ? (
                    <input autoFocus className="input" style={{ padding: '4px 8px', width: '100%' }}
                      value={editingNote?.value ?? ''}
                      onChange={e => setEditingNote({ ip: d.ip, value: e.target.value })}
                      onBlur={saveNote}
                      onKeyDown={e => { if (e.key === 'Enter') saveNote() }} />
                  ) : (
                    <span onClick={() => setEditingNote({ ip: d.ip, value: d.note || d.comment || '' })}
                      style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                      title="点击编辑备注">
                      {d.note || d.comment || '—'} <Pencil size={11} style={{ opacity: 0.35 }} />
                    </span>
                  )}
                </td>
                <td>{d.blocked && <span className="pill pill-danger"><span className="status-dot danger" style={{ width: 6, height: 6 }} />已封禁</span>}</td>
                <td>
                  <div className="flex gap-3">
                    <button onClick={() => openDetail(d.ip)} className="btn-link text-signal">详情</button>
                    {d.blocked
                      ? <button onClick={() => doUnblock(d.ip)} className="btn-link" style={{ color: 'var(--signal)' }}>解封</button>
                      : <button onClick={() => setConfirmBlock(d.ip)} className="btn-link text-danger">封禁</button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !shown.length && (
          <div className="py-12 text-center text-t3 text-[13px]">{search ? '没有匹配的终端' : '暂无终端数据'}</div>
        )}
      </div>

      <ConfirmModal
        open={!!confirmBlock}
        danger
        title={`确认封禁 ${confirmBlock || ''}？`}
        desc="该设备将无法访问外网，局域网互访不受影响，其现有连接会被清除。"
        confirmLabel="确认封禁"
        onClose={() => setConfirmBlock(null)}
        onConfirm={() => { if (confirmBlock) doBlock(confirmBlock); setConfirmBlock(null) }}
      />

      {detail && (
        <div className="drawer animate-in">
          <div className="flex justify-between items-start mb-4">
            <div>
              <div className="mono text-[17px] font-bold">{detail.ip}</div>
              <div className="text-[12.5px] text-t2 mt-0.5">{detail.count} 条活跃会话</div>
            </div>
            <button className="btn" style={{ width: 30, height: 30, padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              onClick={() => setDetail(null)}><X size={14} /></button>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>{['协议', '源', '目标', '方向', '状态', '累计'].map(h => <th key={h}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {detail.sessions.map((s: any) => (
                  <tr key={s.id}>
                    <td><span className="badge badge-gray">{s.protocol}</span></td>
                    <td className="mono">{s.src}</td>
                    <td className="mono">{s.dst}</td>
                    <td>{s.direction === 'out' ? '↑ 出' : '↓ 入'}</td>
                    <td className="text-2">{s.state || '—'}</td>
                    <td className="num">{fmtBytes(s.total_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!detail.sessions.length && <div className="py-8 text-center text-t3 text-[12.5px]">无活跃会话</div>}
          </div>
        </div>
      )}
    </div>
  )
}
