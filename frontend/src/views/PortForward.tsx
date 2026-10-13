import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, Search, Plus, Pencil, Trash2, Network as NetworkIcon } from 'lucide-react'
import api from '../api/client'
import { PageHeader, Skeleton, EmptyState, Segmented } from '../components/ui'
import { Modal, ConfirmModal } from '../components/ui/Modal'
import { useToast } from '../components/ui/Toast'

interface PortForward {
  id: string
  name: string
  protocol: string
  wan_port: string
  target_ip: string
  target_port: string
  in_interface: string
  disabled: boolean
}

export default function PortForward() {
  const [rules, setRules] = useState<PortForward[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'tcp' | 'udp'>('all')
  const [search, setSearch] = useState('')
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<PortForward | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<PortForward | null>(null)
  const [interfaces, setInterfaces] = useState<{ name: string; type: string; running: boolean; disabled: boolean }[]>([])
  const toast = useToast()

  const load = async () => {
    setLoading(true)
    try {
      const [pf, ifs] = await Promise.all([
        api.get('/port-forward').then(r => r.data).catch(() => []),
        api.get('/dashboard/interfaces').then(r => r.data).catch(() => []),
      ])
      setRules(pf || [])
      setInterfaces(ifs || [])
    } catch {
      setRules([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const shown = useMemo(() => {
    const kw = search.trim().toLowerCase()
    return rules.filter(r => {
      const byFilter = filter === 'all' || r.protocol === filter
      const bySearch = !kw || `${r.name} ${r.target_ip} ${r.wan_port} ${r.target_port}`.toLowerCase().includes(kw)
      return byFilter && bySearch
    })
  }, [rules, filter, search])

  const doDelete = async (rule: PortForward) => {
    try {
      await api.delete(`/port-forward/${encodeURIComponent(rule.id)}`)
      toast.push('ok', `已删除 ${rule.name || rule.wan_port}`)
      load()
    } catch (e: any) {
      toast.push('err', e.response?.data?.detail || '删除失败')
    }
  }

  return (
    <div>
      <PageHeader
        title="端口转发"
        desc="将公网/WAN 端口映射到内网设备"
        actions={
          <>
            <button className="btn" onClick={load}><RefreshCw size={14} /> 刷新</button>
            <button className="btn-primary" onClick={() => { setEditing(null); setEditOpen(true) }}>
              <Plus size={14} /> 新增转发
            </button>
          </>
        }
      />

      <div className="flex items-center gap-2.5 mb-3">
        <Segmented size="sm" value={filter} onChange={setFilter} options={[
          { value: 'all', label: `全部 ${rules.length}` },
          { value: 'tcp', label: 'TCP' },
          { value: 'udp', label: 'UDP' }]} />
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-t3" />
          <input className="input pl-9 w-64" placeholder="搜索名称 / IP / 端口" value={search}
            onChange={e => setSearch(e.target.value)} />
        </div>
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {['名称', '协议', 'WAN 端口', '内网 IP', '目标端口', '入口接口', '状态', '操作'].map(h => <th key={h}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {loading ? Array.from({ length: 6 }).map((_, i) => (
              <tr key={i}>{Array.from({ length: 8 }).map((_, j) => <td key={j}><Skeleton h={14} /></td>)}</tr>
            )) : shown.map(rule => (
              <tr key={rule.id} style={{ opacity: rule.disabled ? 0.55 : 1 }}>
                <td style={{ fontWeight: 500 }}>{rule.name || '—'}</td>
                <td>{rule.protocol.toUpperCase()}</td>
                <td className="mono">{rule.wan_port}</td>
                <td className="mono">{rule.target_ip}</td>
                <td className="mono">{rule.target_port || rule.wan_port}</td>
                <td className="mono">{rule.in_interface || '—'}</td>
                <td>{rule.disabled ? <span className="pill pill-off">已禁用</span> : <span className="pill pill-on">启用</span>}</td>
                <td>
                  <div className="flex gap-3">
                    <button className="btn-link btn-link-icon text-t2" onClick={() => { setEditing(rule); setEditOpen(true) }}>
                      <Pencil size={12} /> 编辑
                    </button>
                    <button className="btn-link btn-link-icon text-danger" onClick={() => setConfirmDelete(rule)}>
                      <Trash2 size={12} /> 删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !shown.length && (
          <EmptyState icon={<NetworkIcon size={20} />} title="没有匹配的转发规则"
            desc="点右上角「新增转发」创建端口映射" />
        )}
      </div>

      {editOpen && <PortForwardModal rule={editing} interfaces={interfaces} onClose={() => setEditOpen(false)} onSaved={() => { setEditOpen(false); load() }} />}

      <ConfirmModal open={!!confirmDelete} danger title={`删除转发规则「${confirmDelete?.name || confirmDelete?.wan_port || ''}」？`}
        desc="删除后外部端口将立即不可访问。"
        confirmLabel="确认删除" onClose={() => setConfirmDelete(null)}
        onConfirm={() => { if (confirmDelete) doDelete(confirmDelete); setConfirmDelete(null) }} />
    </div>
  )
}

function PortForwardModal({ rule, interfaces, onClose, onSaved }: {
  rule: PortForward | null
  interfaces: { name: string; type: string; running: boolean; disabled: boolean }[]
  onClose: () => void
  onSaved: () => void
}) {
  const editing = !!rule
  const [form, setForm] = useState({
    name: rule?.name ?? '',
    protocol: rule?.protocol ?? 'tcp',
    wan_port: rule?.wan_port ?? '',
    target_ip: rule?.target_ip ?? '',
    target_port: rule?.target_port ?? '',
    in_interface: rule?.in_interface ?? '',
    disabled: rule?.disabled ?? false,
  })
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const toast = useToast()
  const set = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }))

  const submit = async () => {
    setErr('')
    if (!/^\d+$/.test(form.wan_port.trim()) || +form.wan_port < 1 || +form.wan_port > 65535) {
      setErr('WAN 端口应为 1-65535'); return
    }
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(form.target_ip.trim())) {
      setErr('内网 IP 格式应为 192.168.88.100'); return
    }
    if (form.target_port && !/^\d+$/.test(form.target_port.trim())) {
      setErr('目标端口格式不正确'); return
    }
    setSaving(true)
    try {
      if (editing && rule) {
        await api.patch(`/port-forward/${encodeURIComponent(rule.id)}`, form)
        toast.push('ok', '转发规则已更新')
      } else {
        await api.post('/port-forward', form)
        toast.push('ok', '转发规则已创建')
      }
      onSaved()
    } catch (e: any) {
      setErr(e.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={editing ? '编辑端口转发' : '新增端口转发'} width={480}>
      <div className="space-y-4">
        <div>
          <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pf-name">名称</label>
          <input id="pf-name" className="input" placeholder="例如：管理后台" value={form.name}
            onChange={e => set('name', e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pf-proto">协议</label>
            <select id="pf-proto" className="input" value={form.protocol}
              onChange={e => set('protocol', e.target.value)}>
              <option value="tcp">TCP</option>
              <option value="udp">UDP</option>
            </select>
          </div>
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pf-wan">WAN 端口</label>
            <input id="pf-wan" className="input mono" placeholder="9233" value={form.wan_port}
              onChange={e => set('wan_port', e.target.value)} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pf-ip">内网 IP</label>
            <input id="pf-ip" className="input mono" placeholder="192.168.88.100" value={form.target_ip}
              onChange={e => set('target_ip', e.target.value)} />
          </div>
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pf-target">目标端口（可选）</label>
            <input id="pf-target" className="input mono" placeholder="默认同 WAN 端口" value={form.target_port}
              onChange={e => set('target_port', e.target.value)} />
          </div>
        </div>
        <div>
          <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pf-if">入口接口</label>
          <select id="pf-if" className="input" value={form.in_interface}
            onChange={e => set('in_interface', e.target.value)}>
            <option value="">全部接口</option>
            {interfaces.map(i => (
              <option key={i.name} value={i.name}>{i.name}（{i.type}{i.running ? '' : ' · 未运行'}）</option>
            ))}
            {form.in_interface && !interfaces.some(i => i.name === form.in_interface) && (
              <option value={form.in_interface}>{form.in_interface}</option>
            )}
          </select>
        </div>
        {editing && (
          <label className="flex items-center gap-2 text-sm text-2">
            <input type="checkbox" checked={form.disabled} onChange={e => set('disabled', e.target.checked)} />
            禁用规则
          </label>
        )}
        {err && <div className="rounded-ctrl px-3 py-2 text-[12.5px]"
          style={{ background: 'var(--danger-dim)', color: 'var(--danger)' }}>{err}</div>}
        <div className="flex gap-3 pt-1">
          <button className="btn flex-1" onClick={onClose}>取消</button>
          <button className="btn-primary flex-1" disabled={saving} onClick={submit}>
            {saving ? '保存中…' : editing ? '保存修改' : '创建'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
