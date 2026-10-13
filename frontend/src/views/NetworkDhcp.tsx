/**
 * 网络 → DHCP 子页。
 *
 * 功能：
 *  - DHCP 服务器：读取 / 新增 / 编辑 / 删除
 *  - 网段配置：读取
 *  - 租约：动态租约「绑定静态」（make-static，快速固定 MAC↔IP）
 *  - 租约：静态绑定删除
 *  - 新增静态绑定：可从在线设备下拉直接选 MAC，避免手抄
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Network as NetworkIcon, Plus, RefreshCw, Search, Trash2, Link2, Server, Router, Pencil, Layers, CheckCircle2,
} from 'lucide-react'
import api from '../api/client'
import { Segmented, Skeleton, EmptyState, PageHeader, Switch } from '../components/ui'
import { Modal, ConfirmModal } from '../components/ui/Modal'
import { useToast } from '../components/ui/Toast'

interface Lease {
  id: string
  address: string
  mac: string
  hostname: string
  server: string
  status: string
  comment: string
  last_seen: string
  expires_after: string
  dynamic: boolean
  is_static: boolean
  disabled: boolean
}
interface ServerInfo {
  id: string; name: string; interface: string; address_pool: string
  lease_time: string; disabled: boolean
}
interface NetInfo {
  id: string; address: string; gateway: string; netmask: string
  dns_server: string; domain: string; comment: string
}
interface IfaceInfo { name: string; type: string; running: boolean; disabled: boolean }
interface IpPoolInfo { id: string; name: string; ranges: string; comment: string }

export default function NetworkDhcp() {
  const [leases, setLeases] = useState<Lease[]>([])
  const [servers, setServers] = useState<ServerInfo[]>([])
  const [networks, setNetworks] = useState<NetInfo[]>([])
  const [pools, setPools] = useState<IpPoolInfo[]>([])
  const [interfaces, setInterfaces] = useState<IfaceInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'dynamic' | 'static'>('all')
  const [search, setSearch] = useState('')
  const [confirmStatic, setConfirmStatic] = useState<Lease | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<Lease | null>(null)
  const [serverModal, setServerModal] = useState<{ mode: 'create' | 'edit'; server?: ServerInfo } | null>(null)
  const [networkModal, setNetworkModal] = useState<{ mode: 'create' | 'edit'; network?: NetInfo } | null>(null)
  const [poolModal, setPoolModal] = useState<{ mode: 'create' | 'edit'; pool?: IpPoolInfo } | null>(null)
  const [provisionOpen, setProvisionOpen] = useState(() => new URLSearchParams(location.search).get('new') === '1')
  const toast = useToast()

  const load = async () => {
    setLoading(true)
    try {
      const [ov, ls, ifs] = await Promise.all([
        api.get('/network/dhcp').then(r => r.data).catch(() => ({ servers: [], networks: [] })),
        api.get('/network/dhcp/leases').then(r => r.data).catch(() => []),
        api.get('/dashboard/interfaces').then(r => r.data).catch(() => []),
      ])
      setServers(ov.servers || [])
      setNetworks(ov.networks || [])
      setPools(ov.pools || [])
      setLeases(ls || [])
      setInterfaces(ifs || [])
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const doMakeStatic = async (lease: Lease) => {
    try {
      await api.post('/network/dhcp/leases/make-static', { lease_id: lease.id })
      toast.push('ok', `${lease.address} 已绑定为静态地址`)
      load()
    } catch (e: any) {
      toast.push('err', e.response?.data?.detail || '绑定失败')
    }
  }

  const doDeleteLease = async (lease: Lease) => {
    try {
      await api.delete(`/network/dhcp/leases/${encodeURIComponent(lease.id)}`)
      toast.push('ok', `已删除 ${lease.address} 的静态绑定`)
      load()
    } catch (e: any) {
      toast.push('err', e.response?.data?.detail || '删除失败')
    }
  }

  const shown = useMemo(() => {
    const kw = search.trim().toLowerCase()
    return leases.filter(l => {
      const byFilter = filter === 'all' ? true : filter === 'dynamic' ? l.dynamic : l.is_static
      const bySearch = !kw || l.address.includes(kw) || (l.mac || '').toLowerCase().includes(kw)
        || (l.hostname || '').toLowerCase().includes(kw) || (l.comment || '').toLowerCase().includes(kw)
      return byFilter && bySearch
    })
  }, [leases, filter, search])

  const dynamicCount = leases.filter(l => l.dynamic).length
  const staticCount = leases.filter(l => l.is_static).length

  return (
    <div>
      <PageHeader
        title="DHCP 地址分配"
        desc={<>管理 DHCP 服务器与地址绑定 · 动态 {dynamicCount} 条 / 静态 {staticCount} 条</>}
        actions={
          <>
            <button className="btn" onClick={load} title="刷新"><RefreshCw size={14} /> 刷新</button>
            <button className="btn-primary" onClick={() => setProvisionOpen(true)}><Plus size={14} /> 新建 DHCP 服务</button>
          </>
        }
      />

      {/* DHCP 服务器 + 网段 */}
      <div className="grid gap-3.5 mb-4 lg:grid-cols-3">
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3.5">
            <div className="flex items-center gap-2 text-[13.5px] font-semibold">
              <Server size={15} className="text-t2" /> DHCP 服务器
            </div>
          </div>
          {loading ? <Skeleton h={54} /> : servers.length ? (
            <div className="flex flex-col gap-2.5">
              {servers.map(s => (
                <div key={s.id} className="rounded-ctrl border border-[var(--border)] px-3.5 py-2.5">
                  <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
                    <span className="text-[13px] font-semibold">{s.name}</span>
                    <span className="text-[12px] text-t3">接口 <span className="mono text-t2">{s.interface}</span></span>
                    <span className="text-[12px] text-t3">地址池 <span className="mono text-t2">{s.address_pool || '—'}</span></span>
                    <span className="text-[12px] text-t3">租期 <span className="mono text-t2">{s.lease_time || '—'}</span></span>
                    {s.disabled && <span className="pill pill-off">已禁用</span>}
                    <span className="flex gap-3 ml-auto">
                      <button className="btn-link btn-link-icon text-t2"
                        onClick={() => setServerModal({ mode: 'edit', server: s })}>
                        <Pencil size={12} /> 编辑
                      </button>
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : <EmptyState icon={<Server size={22} />} title="未发现 DHCP 服务器"
                 desc="可以用右上角「新增」为某个接口建立 DHCP 服务" />}
        </div>

        <div className="card p-5">
          <div className="flex items-center justify-between mb-3.5">
            <div className="flex items-center gap-2 text-[13.5px] font-semibold">
              <Router size={15} className="text-t2" /> 网段配置
            </div>
          </div>
          {loading ? <Skeleton h={54} /> : networks.length ? (
            <div className="flex flex-col gap-2.5">
              {networks.map(n => (
                <div key={n.id} className="rounded-ctrl border border-[var(--border)] px-3.5 py-2.5">
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
                    <span className="mono text-[13px] font-semibold">{n.address}{n.netmask ? ` / ${n.netmask}` : ''}</span>
                    <span className="flex gap-3 ml-auto">
                      <button className="btn-link btn-link-icon text-t2"
                        onClick={() => setNetworkModal({ mode: 'edit', network: n })}>
                        <Pencil size={12} /> 编辑
                      </button>
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-x-5 gap-y-1 mt-1 text-[12px] text-t3">
                    <span>网关 <span className="mono text-t2">{n.gateway || '—'}</span></span>
                    <span>DNS <span className="mono text-t2">{n.dns_server || '—'}</span></span>
                    {n.domain && <span>域 <span className="mono text-t2">{n.domain}</span></span>}
                    {n.comment && <span>{n.comment}</span>}
                  </div>
                </div>
              ))}
            </div>
          ) : <EmptyState icon={<Router size={22} />} title="未发现网段配置"
                 desc="点右上角「新增」为 DHCP 服务器所在网段配置网关与 DNS" />}
        </div>
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3.5">
            <div className="flex items-center gap-2 text-[13.5px] font-semibold">
              <Layers size={15} className="text-t2" /> 地址池
            </div>
          </div>
          {loading ? <Skeleton h={54} /> : pools.length ? (
            <div className="flex flex-col gap-2.5">
              {pools.map(p => (
                <div key={p.id} className="rounded-ctrl border border-[var(--border)] px-3.5 py-2.5">
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
                    <span className="mono text-[13px] font-semibold">{p.name}</span>
                    <span className="flex gap-3 ml-auto">
                      <button className="btn-link btn-link-icon text-t2"
                        onClick={() => setPoolModal({ mode: 'edit', pool: p })}>
                        <Pencil size={12} /> 编辑
                      </button>
                    </span>
                  </div>
                  <div className="mono text-[12px] text-t2 mt-1">{p.ranges || '—'}</div>
                  {p.comment && <div className="text-[11.5px] text-t3 mt-0.5">{p.comment}</div>}
                </div>
              ))}
            </div>
          ) : <EmptyState icon={<Layers size={22} />} title="未发现地址池"
                 desc="用「新建 DHCP 服务」会自动创建，也可以在这里单独新增" />}
        </div>
      </div>

      {/* 租约表 */}
      <div className="page-head">
        <div>
          <div className="page-title">地址租约与静态绑定</div>
          <div className="page-desc">动态租约可一键「绑定静态」，固定该设备的 MAC 与 IP 对应关系</div>
        </div>
        <div className="flex items-center gap-2.5 flex-wrap">
          <Segmented size="sm" value={filter} onChange={setFilter} options={[
            { value: 'all', label: `全部 ${leases.length}` },
            { value: 'dynamic', label: `动态 ${dynamicCount}` },
            { value: 'static', label: `静态 ${staticCount}` }]} />
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-t3" />
            <input className="input pl-9 w-56" placeholder="搜索 IP / MAC / 主机名" value={search}
              onChange={e => setSearch(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {['', 'IP 地址', 'MAC 地址', '主机名', '备注', '服务器', '状态', '类型', '最近活跃', '操作'].map((h, i) =>
                <th key={i}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {loading ? Array.from({ length: 6 }).map((_, i) => (
              <tr key={i}>{Array.from({ length: 10 }).map((_, j) => <td key={j}><Skeleton h={14} /></td>)}</tr>
            )) : shown.map(l => (
              <tr key={l.id} style={{ opacity: l.disabled ? 0.5 : 1 }}>
                <td style={{ width: 40, paddingRight: 0 }}>
                  <span className={`status-dot ${l.dynamic ? 'off' : 'on'}`} style={{ width: 6, height: 6 }} />
                </td>
                <td className="mono" style={{ fontWeight: 500 }}>{l.address}</td>
                <td className="mono text-2">{l.mac}</td>
                <td style={{ fontWeight: 500 }}>{l.hostname || '—'}</td>
                <td className="text-2">{l.comment || '—'}</td>
                <td className="text-2 mono">{l.server}</td>
                <td className="text-2">{l.status === 'bound' ? '已绑定' : l.status || '—'}</td>
                <td>{l.dynamic
                  ? <span className="pill pill-off">动态</span>
                  : <span className="pill pill-on">静态</span>}</td>
                <td className="text-3 text-[12px]">{l.last_seen || '—'}</td>
                <td>
                  <div className="flex gap-3">
                    {l.dynamic && (
                      <button className="btn-link btn-link-icon text-signal"
                        title="把该设备的 MAC 与当前 IP 固定为静态绑定"
                        onClick={() => setConfirmStatic(l)}>
                        <Link2 size={12} /> 绑定静态
                      </button>
                    )}
                    {l.is_static && (
                      <button className="btn-link btn-link-icon text-danger" onClick={() => setConfirmDelete(l)}>
                        <Trash2 size={12} /> 删除
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !shown.length && (
          <EmptyState icon={<NetworkIcon size={22} />} title="没有匹配的租约" desc="换一个筛选条件或搜索关键字试试" />
        )}
      </div>

      <ConfirmModal
        open={!!confirmStatic}
        title={`将 ${confirmStatic?.address || ''} 绑定为静态地址？`}
        desc={confirmStatic
          ? `设备 ${confirmStatic.mac}${confirmStatic.hostname ? '（' + confirmStatic.hostname + '）' : ''} 以后每次都会固定拿到 ${confirmStatic.address}。`
          : ''}
        confirmLabel="确认绑定"
        onClose={() => setConfirmStatic(null)}
        onConfirm={() => { if (confirmStatic) doMakeStatic(confirmStatic); setConfirmStatic(null) }}
      />
      <ConfirmModal
        open={!!confirmDelete} danger
        title={`删除 ${confirmDelete?.address || ''} 的静态绑定？`}
        desc="删除后该设备会重新走动态分配，可能拿到不同地址。"
        confirmLabel="确认删除"
        onClose={() => setConfirmDelete(null)}
        onConfirm={() => { if (confirmDelete) doDeleteLease(confirmDelete); setConfirmDelete(null) }}
      />

      {serverModal && <ServerModal state={serverModal} interfaces={interfaces}
        onClose={() => setServerModal(null)} onSaved={() => { setServerModal(null); load() }} />}
      {poolModal && <PoolModal state={poolModal}
        onClose={() => setPoolModal(null)} onSaved={() => { setPoolModal(null); load() }} />}
      {provisionOpen && <ProvisionModal interfaces={interfaces}
        onClose={() => setProvisionOpen(false)} onSaved={() => { setProvisionOpen(false); load() }} />}
      {networkModal && <NetworkModal state={networkModal}
        onClose={() => setNetworkModal(null)} onSaved={() => { setNetworkModal(null); load() }} />}
    </div>
  )
}

/** 编辑 DHCP 服务器 */
function ServerModal({ state, interfaces, onClose, onSaved }: {
  state: { mode: 'create' | 'edit'; server?: ServerInfo }
  interfaces: IfaceInfo[]
  onClose: () => void
  onSaved: () => void
}) {
  const editing = state.mode === 'edit'
  const [form, setForm] = useState({
    name: state.server?.name ?? 'dhcp-lan',
    interface: state.server?.interface ?? (interfaces[0]?.name || ''),
    address_pool: state.server?.address_pool ?? '',
    lease_time: state.server?.lease_time ?? '1d',
    disabled: state.server?.disabled ?? false,
  })
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const toast = useToast()

  const submit = async () => {
    setErr('')
    if (!form.name.trim()) { setErr('服务器名不能为空'); return }
    if (!form.interface.trim()) { setErr('必须选择接口'); return }
    setSaving(true)
    try {
      if (editing && state.server) {
        await api.patch(`/network/dhcp/servers/${encodeURIComponent(state.server.id)}`, {
          name: form.name.trim(), interface: form.interface.trim(),
          address_pool: form.address_pool.trim(), lease_time: form.lease_time.trim(),
          disabled: form.disabled,
        })
        toast.push('ok', `已更新 DHCP 服务器 ${form.name}`)
      } else {
        setErr('DHCP 服务器请通过右上角「新建 DHCP 服务」创建')
        return
      }
      onSaved()
    } catch (e: any) {
      setErr(e.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="编辑 DHCP 服务器" width={480}>
      <div className="space-y-4">
        <div>
          <label className="block text-[12px] text-t2 mb-1.5" htmlFor="sv-name">服务器名</label>
          <input id="sv-name" className="input" value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
        </div>
        <div>
          <label className="block text-[12px] text-t2 mb-1.5" htmlFor="sv-if">接口</label>
          <select id="sv-if" className="input" value={form.interface}
            onChange={e => setForm(f => ({ ...f, interface: e.target.value }))}>
            {interfaces.map(i => (
              <option key={i.name} value={i.name}>{i.name}（{i.type}{i.running ? '' : ' · 未运行'}）</option>
            ))}
            {form.interface && !interfaces.some(i => i.name === form.interface) && (
              <option value={form.interface}>{form.interface}</option>
            )}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="sv-pool">地址池（可选）</label>
            <input id="sv-pool" className="input mono" placeholder="dhcp-lan" value={form.address_pool}
              onChange={e => setForm(f => ({ ...f, address_pool: e.target.value }))} />
          </div>
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="sv-lease">租期</label>
            <input id="sv-lease" className="input mono" placeholder="1d / 12h / 00:30:00" value={form.lease_time}
              onChange={e => setForm(f => ({ ...f, lease_time: e.target.value }))} />
          </div>
        </div>
        {editing && (
          <Switch checked={!form.disabled} onChange={v => setForm(f => ({ ...f, disabled: !v }))}
            label={form.disabled ? '已禁用' : '已启用'} />
        )}
        <p className="text-[12px] text-t3">
          新建请使用右上角「新建 DHCP 服务」；这里只编辑已有服务器。
        </p>
        {err && <div className="rounded-ctrl px-3 py-2 text-[12.5px]"
          style={{ background: 'var(--danger-dim)', color: 'var(--danger)' }}>{err}</div>}
        <div className="flex gap-3 pt-1">
          <button className="btn flex-1" onClick={onClose}>取消</button>
          <button className="btn-primary flex-1" disabled={saving} onClick={submit}>
            {saving ? '提交中…' : editing ? '保存修改' : '创建'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** 编辑 DHCP 网段（决定客户端拿到的网关与 DNS） */
function NetworkModal({ state, onClose, onSaved }: {
  state: { mode: 'create' | 'edit'; network?: NetInfo }
  onClose: () => void
  onSaved: () => void
}) {
  const editing = state.mode === 'edit'
  const [form, setForm] = useState({
    address: state.network?.address ?? '',
    gateway: state.network?.gateway ?? '',
    netmask: state.network?.netmask ?? '',
    dns_server: state.network?.dns_server ?? '',
    domain: state.network?.domain ?? '',
    comment: state.network?.comment ?? '',
  })
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const toast = useToast()

  const submit = async () => {
    setErr('')
    if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(form.address.trim())) {
      setErr('网段格式应为 192.168.8.0/24')
      return
    }
    setSaving(true)
    try {
      const payload = {
        address: form.address.trim(), gateway: form.gateway.trim(), netmask: form.netmask.trim(),
        dns_server: form.dns_server.trim(), domain: form.domain.trim(), comment: form.comment.trim(),
      }
      if (editing && state.network) {
        await api.patch(`/network/dhcp/networks/${encodeURIComponent(state.network.id)}`, payload)
        toast.push('ok', `已更新网段 ${payload.address}`)
      } else {
        setErr('网段请通过右上角「新建 DHCP 服务」创建')
        return
      }
      onSaved()
    } catch (e: any) {
      setErr(e.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="编辑 DHCP 网段" width={480}>
      <div className="space-y-4">
        <div>
          <label className="block text-[12px] text-t2 mb-1.5" htmlFor="nw-addr">网段地址</label>
          <input id="nw-addr" className="input mono" placeholder="192.168.8.0/24" value={form.address}
            onChange={e => setForm(f => ({ ...f, address: e.target.value }))} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="nw-gw">网关</label>
            <input id="nw-gw" className="input mono" placeholder="192.168.8.1" value={form.gateway}
              onChange={e => setForm(f => ({ ...f, gateway: e.target.value }))} />
          </div>
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="nw-mask">子网掩码（可选）</label>
            <input id="nw-mask" className="input mono" placeholder="255.255.255.0" value={form.netmask}
              onChange={e => setForm(f => ({ ...f, netmask: e.target.value }))} />
          </div>
        </div>
        <div>
          <label className="block text-[12px] text-t2 mb-1.5" htmlFor="nw-dns">DNS 服务器（可多个，逗号分隔）</label>
          <input id="nw-dns" className="input mono" placeholder="192.168.8.1,223.5.5.5" value={form.dns_server}
            onChange={e => setForm(f => ({ ...f, dns_server: e.target.value }))} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="nw-domain">域名（可选）</label>
            <input id="nw-domain" className="input" placeholder="lan" value={form.domain}
              onChange={e => setForm(f => ({ ...f, domain: e.target.value }))} />
          </div>
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="nw-note">备注（可选）</label>
            <input id="nw-note" className="input" placeholder="LAN network" value={form.comment}
              onChange={e => setForm(f => ({ ...f, comment: e.target.value }))} />
          </div>
        </div>
        {err && <div className="rounded-ctrl px-3 py-2 text-[12.5px]"
          style={{ background: 'var(--danger-dim)', color: 'var(--danger)' }}>{err}</div>}
        <div className="flex gap-3 pt-1">
          <button className="btn flex-1" onClick={onClose}>取消</button>
          <button className="btn-primary flex-1" disabled={saving} onClick={submit}>
            {saving ? '提交中…' : editing ? '保存修改' : '创建'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** 地址池：编辑 */
function PoolModal({ state, onClose, onSaved }: {
  state: { mode: 'create' | 'edit'; pool?: IpPoolInfo }
  onClose: () => void
  onSaved: () => void
}) {
  const editing = state.mode === 'edit'
  const [form, setForm] = useState({
    name: state.pool?.name ?? '', ranges: state.pool?.ranges ?? '', comment: state.pool?.comment ?? '',
  })
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const toast = useToast()

  const submit = async () => {
    setErr('')
    if (!form.name.trim()) { setErr('地址池名不能为空'); return }
    if (!/^[\d.,\-\s]+$/.test(form.ranges.trim())) { setErr('地址范围格式如 192.168.8.100-192.168.8.200'); return }
    setSaving(true)
    try {
      if (editing && state.pool) {
        await api.patch(`/network/dhcp/pools/${encodeURIComponent(state.pool.id)}`, {
          name: form.name.trim(), ranges: form.ranges.trim(), comment: form.comment.trim(),
        })
        toast.push('ok', `已更新地址池 ${form.name}`)
      } else {
        // PoolModal only supports editing now. New pools are created
        // through the one-stop DHCP provision flow.
        setErr('地址池请通过右上角「新建 DHCP 服务」创建')
        return
      }
      onSaved()
    } catch (e: any) {
      setErr(e.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={editing ? '编辑地址池' : '编辑地址池'} width={460}>
      <div className="space-y-4">
        <div>
          <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pl-name">地址池名</label>
          <input id="pl-name" className="input mono" placeholder="dhcp-lan" value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
        </div>
        <div>
          <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pl-range">地址范围</label>
          <input id="pl-range" className="input mono" placeholder="192.168.8.100-192.168.8.200" value={form.ranges}
            onChange={e => setForm(f => ({ ...f, ranges: e.target.value }))} />
        </div>
        <div>
          <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pl-note">备注（可选）</label>
          <input id="pl-note" className="input" value={form.comment}
            onChange={e => setForm(f => ({ ...f, comment: e.target.value }))} />
        </div>
        {err && <div className="rounded-ctrl px-3 py-2 text-[12.5px]"
          style={{ background: 'var(--danger-dim)', color: 'var(--danger)' }}>{err}</div>}
        <div className="flex gap-3 pt-1">
          <button className="btn flex-1" onClick={onClose}>取消</button>
          <button className="btn-primary flex-1" disabled={saving} onClick={submit}>
            {saving ? '提交中…' : editing ? '保存修改' : '创建'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/**
 * 一站式「新建 DHCP 服务」。
 */
function ProvisionModal({ interfaces, onClose, onSaved }: {
  interfaces: IfaceInfo[]
  onClose: () => void
  onSaved: () => void
}) {
  const defaultIface = interfaces.find(i => i.type === 'bridge' && i.running)?.name
    || interfaces.find(i => i.running)?.name || interfaces[0]?.name || ''
  const [form, setForm] = useState({
    octets: '192.168.88',
    prefix: '24',
    gateway: '192.168.88.1',
    pool_name: 'dhcp-lan',
    range_start: '192.168.88.100',
    range_end: '192.168.88.200',
    server_name: 'dhcp-lan',
    interface: defaultIface,
    dns_server: '192.168.88.1',
    lease_time: '1d',
    comment: '',
  })
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [steps, setSteps] = useState<any[] | null>(null)
  const toast = useToast()
  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  /** 改网段前三段时，自动推导网关/地址范围/DNS/名称，用户仍可覆盖 */
  const onOctets = (v: string) => {
    setForm(f => ({
      ...f,
      octets: v,
      gateway: v ? `${v}.1` : '',
      range_start: v ? `${v}.100` : '',
      range_end: v ? `${v}.200` : '',
      dns_server: v ? `${v}.1` : '',
      pool_name: f.pool_name === 'dhcp-lan' ? 'dhcp-lan' : f.pool_name,
    }))
  }

  const ranges = `${form.range_start}-${form.range_end}`
  const cidr = `${form.octets}.0/${form.prefix}`

  const submit = async () => {
    setErr('')
    if (!/^\d{1,3}(\.\d{1,3}){2}$/.test(form.octets)) { setErr('网段前三段格式如 192.168.88'); return }
    if (!form.server_name.trim() || !form.pool_name.trim()) { setErr('名称不能为空'); return }
    if (!form.interface) { setErr('请选择接口'); return }
    setSaving(true)
    try {
      const { data } = await api.post('/network/dhcp/provision', {
        network_cidr: cidr, gateway: form.gateway.trim(), pool_name: form.pool_name.trim(),
        pool_ranges: ranges, server_name: form.server_name.trim(), interface: form.interface,
        dns_server: form.dns_server.trim(), lease_time: form.lease_time.trim(), comment: form.comment.trim(),
      })
      setSteps(data.steps || [])
      toast.push('ok', 'DHCP 服务已创建')
      setTimeout(onSaved, 1600)
    } catch (e: any) {
      setErr(e.response?.data?.detail || '创建失败')
    } finally {
      setSaving(false)
    }
  }

  const ACTION_TEXT: Record<string, string> = { created: '新建', updated: '更新', exists: '已存在，复用' }

  return (
    <Modal open onClose={onClose} title="新建 DHCP 服务" width={560}>
      {steps ? (
        <div className="space-y-3">
          <div className="text-[13px] text-t2">面板已按正确顺序完成以下操作：</div>
          {steps.map((st, i) => (
            <div key={i} className="flex items-start gap-2.5 rounded-ctrl border border-[var(--border)] px-3.5 py-2.5">
              <CheckCircle2 size={15} style={{ color: 'var(--signal)', marginTop: 2 }} />
              <div>
                <div className="text-[13px] font-medium">
                  {st.step === 'pool' ? '地址池' : st.step === 'network' ? '网段' : 'DHCP 服务器'}：
                  <span className="mono"> {st.name}</span>
                  <span className="text-t3 font-normal">（{ACTION_TEXT[st.action] || st.action}）</span>
                </div>
                <div className="text-[12px] text-t3 mt-0.5">{st.detail}</div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-net">网段前三段</label>
              <input id="pv-net" className="input mono" placeholder="192.168.88" value={form.octets}
                onChange={e => onOctets(e.target.value)} />
            </div>
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-prefix">掩码位数</label>
              <input id="pv-prefix" className="input mono" value={form.prefix}
                onChange={e => set('prefix', e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-gw">网关</label>
              <input id="pv-gw" className="input mono" value={form.gateway}
                onChange={e => set('gateway', e.target.value)} />
            </div>
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-dns">DNS</label>
              <input id="pv-dns" className="input mono" placeholder="192.168.88.1,223.5.5.5" value={form.dns_server}
                onChange={e => set('dns_server', e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-rs">可分配起始</label>
              <input id="pv-rs" className="input mono" value={form.range_start}
                onChange={e => set('range_start', e.target.value)} />
            </div>
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-re">可分配结束</label>
              <input id="pv-re" className="input mono" value={form.range_end}
                onChange={e => set('range_end', e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-if">接口</label>
              <select id="pv-if" className="input" value={form.interface}
                onChange={e => set('interface', e.target.value)}>
                {interfaces.map(i => (
                  <option key={i.name} value={i.name}>{i.name}（{i.type}{i.running ? '' : ' · 未运行'}）</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-lease">租期</label>
              <input id="pv-lease" className="input mono" placeholder="1d / 12h" value={form.lease_time}
                onChange={e => set('lease_time', e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-sn">DHCP 服务器名</label>
              <input id="pv-sn" className="input mono" value={form.server_name}
                onChange={e => set('server_name', e.target.value)} />
            </div>
            <div>
              <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pv-pn">地址池名</label>
              <input id="pv-pn" className="input mono" value={form.pool_name}
                onChange={e => set('pool_name', e.target.value)} />
            </div>
          </div>

          <div className="flex items-center gap-3">
            {err && <div className="rounded-ctrl px-3 py-2 text-[12.5px] flex-1"
              style={{ background: 'var(--danger-dim)', color: 'var(--danger)' }}>{err}</div>}
            <button className="btn px-5" onClick={onClose}>取消</button>
            <button className="btn-primary px-5" disabled={saving} onClick={submit}>
              {saving ? '创建中…' : '一键创建'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
