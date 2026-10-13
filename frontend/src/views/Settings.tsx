import { useEffect, useState } from 'react'
import { Trash2, Pencil, Star, RefreshCw, Download } from 'lucide-react'
import api from '../api/client'
import { Modal, ConfirmModal } from '../components/ui/Modal'
import { Switch } from '../components/ui'
import { useToast } from '../components/ui/Toast'
import { useUi } from '../lib/store'

interface DeviceRow {
  id: number
  name: string
  host: string
  port: number
  username: string
  auth_method: string
  verify_tls: boolean
  timeout: number
  is_default: boolean
}

export default function Settings() {
  const [devices, setDevices] = useState<DeviceRow[]>([])
  const [msg, setMsg] = useState('')
  const [editing, setEditing] = useState<DeviceRow | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [pwdForm, setPwdForm] = useState({ old_password: '', new_password: '' })
  const [recResult, setRecResult] = useState<{ router: number; added: number; removed: number } | null>(null)
  const [showPwd, setShowPwd] = useState(false)
  const [pwdMsg, setPwdMsg] = useState('')
  const [confirmDel, setConfirmDel] = useState<{ id: number; name: string } | null>(null)
  const [confirmRec, setConfirmRec] = useState(false)
  const [bkSensitive, setBkSensitive] = useState(false)
  const [exporting, setExporting] = useState(false)
  const toast = useToast()
  const { fx, setFx } = useUi()

  const load = () => api.get('/wizard/devices').then(r => setDevices(r.data)).catch(() => {})
  useEffect(() => { load() }, [])

  // 导出 RSC 配置：后端走 SSH 执行 /export，浏览器直接收流下载
  const exportRsc = async () => {
    setExporting(true)
    try {
      const res = await api.get('/backup/export', {
        params: { sensitive: bkSensitive },
        responseType: 'blob',
      })
      const disp = String(res.headers['content-disposition'] || '')
      const match = /filename="?([^";]+)"?/.exec(disp)
      const ts = new Date()
      const pad = (n: number) => String(n).padStart(2, '0')
      const fallback = `ros_${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}`
        + `_${pad(ts.getHours())}${pad(ts.getMinutes())}${pad(ts.getSeconds())}.rsc`
      const name = match?.[1] || fallback

      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast.push('ok', `配置已导出：${name}`)
    } catch (e: any) {
      // 这里响应是 blob，错误详情得先转成文本再解析
      let detail = ''
      const data = e.response?.data
      if (data instanceof Blob) {
        try { detail = JSON.parse(await data.text())?.detail || '' } catch {}
      } else if (data?.detail) {
        detail = data.detail
      }
      toast.push('err', detail || '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const del = async (id: number, name: string) => {
    await api.delete(`/wizard/devices/${id}`).catch(() => {})
    setConfirmDel(null)
    toast.push('ok', `已删除「${name}」`)
    load()
  }
  const setDefault = async (id: number) => {
    await api.post(`/wizard/devices/${id}/default`)
    setMsg('已设为默认设备')
    load()
  }
  const reconcile = async () => {
    setConfirmRec(false)
    try {
      const { data } = await api.post('/firewall/reconcile')
      setRecResult({ router: data.router.length, added: data.added.length, removed: data.removed.length })
      toast.push('ok', '对账完成')
    } catch (e: any) { toast.push('err', e.response?.data?.detail || '对账失败') }
  }

  const changePwd = async () => {
    setPwdMsg('')
    try {
      await api.post('/wizard/change-password', pwdForm)
      setPwdMsg('密码修改成功')
      setPwdForm({ old_password: '', new_password: '' })
    } catch (e: any) {
      setPwdMsg(e.response?.data?.detail || '修改失败')
    }
  }

  return (
    <div className="space-y-5 max-w-[960px] mx-auto animate-in">
      <h1 className="text-[20px] font-bold tracking-tight">设置</h1>

      

      {/* 设备管理 */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>路由器设备</div>
          <button onClick={() => setShowAdd(true)} className="btn-primary px-4 py-2 text-sm text-white">+ 添加设备</button>
        </div>
        <div className="space-y-2">
          {devices.map(d => (
            <div key={d.id} className="flex items-center justify-between rounded-xl px-5 py-3.5" style={{ background: 'var(--hover)', border: '1px solid var(--border)' }}>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 550 }}>
                  {d.name}
                  {d.is_default && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded-md font-semibold" style={{ background: 'var(--signal-dim)', color: 'var(--signal)' }}>默认</span>}
                </div>
                <div className="mono text-3" style={{ fontSize: 11.5, marginTop: 2 }}>
                  {d.host}:{d.port} · {d.username} · {d.auth_method.toUpperCase()}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {!d.is_default && <button onClick={() => setDefault(d.id)} className="text-xs font-medium text-t2 hover:text-t1">设默认</button>}
                <button onClick={() => setEditing(d)} className="text-xs font-medium" style={{ color: 'var(--text-2)' }}>编辑</button>
                <button onClick={() => setConfirmDel({ id: d.id, name: d.name })} className="text-xs font-medium" style={{ color: 'var(--danger)' }}>删除</button>
              </div>
            </div>
          ))}
          {!devices.length && <div className="text-center text-3 text-sm py-8">暂无设备</div>}
        </div>
      </div>

      {/* 修改密码 */}
      <div className="card p-6 space-y-4">
        <div style={{ fontSize: 13.5, fontWeight: 600 }}>修改面板密码</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pwd-old">原密码</label>
            <input id="pwd-old" className="input" style={{ padding: '10px 12px' }} type="password" autoComplete="current-password"
              value={pwdForm.old_password} onChange={e => setPwdForm(f => ({ ...f, old_password: e.target.value }))} />
          </div>
          <div>
            <label className="block text-[12px] text-t2 mb-1.5" htmlFor="pwd-new">新密码（至少 6 位）</label>
            <div className="relative">
              <input id="pwd-new" className="input pr-14" style={{ padding: '10px 44px 10px 12px' }}
                type={showPwd ? 'text' : 'password'} autoComplete="new-password"
                value={pwdForm.new_password} onChange={e => setPwdForm(f => ({ ...f, new_password: e.target.value }))} />
              <button type="button" onClick={() => setShowPwd(v => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[11.5px] text-t3 hover:text-t1 cursor-pointer">
                {showPwd ? '隐藏' : '显示'}
              </button>
            </div>
          </div>
        </div>
        {pwdMsg && <div className="text-[13px]" style={{ color: pwdMsg.includes('成功') ? 'var(--signal)' : 'var(--danger)' }}>{pwdMsg}</div>}
        <button onClick={changePwd} disabled={!pwdForm.old_password || pwdForm.new_password.length < 6} className="h-9 px-5 rounded-ctrl text-[13px] font-semibold text-black cursor-pointer hover:opacity-90 disabled:opacity-40" style={{ background: 'var(--signal)' }}>保存新密码</button>
      </div>

      {/* 配置备份 */}
      <div className="card p-6 space-y-4">
        <div style={{ fontSize: 13.5, fontWeight: 600 }}>配置备份</div>
        <p className="text-sm text-3">
          把路由器当前配置导出为 RSC 文本脚本（<span className="mono">/export</span>）。
          文件直接下载到你电脑，路由器上不会留下任何文件。
        </p>
        <div className="text-[12px] rounded-ctrl px-3 py-2"
          style={{ background: 'var(--hover)', color: 'var(--text-2)' }}>
          此功能依赖路由器的 SSH 服务：请确保路由器已启用 SSH，且面板账户拥有
          <span className="mono"> ssh </span>策略。
        </div>
        <Switch checked={bkSensitive} onChange={setBkSensitive} label="包含密码等敏感信息" />
        {bkSensitive && (
          <div className="text-[12px] rounded-ctrl px-3 py-2"
            style={{ background: 'var(--danger-dim)', color: 'var(--danger)' }}>
            敏感模式会把密码、密钥等明文写进文件，请妥善保管下载到的 .rsc。
          </div>
        )}
        <button onClick={exportRsc} disabled={exporting} className="btn">
          <Download size={14} /> {exporting ? '导出中…' : '导出配置（.rsc）'}
        </button>
      </div>

      {/* 防火墙对账 */}
      <div className="card p-6 space-y-4">
        <div style={{ fontSize: 13.5, fontWeight: 600 }}>防火墙对账</div>
        <p className="text-sm text-3">将面板记录的封禁列表与路由器实际规则同步，以路由器为准。</p>
        {recResult && (
          <div className="grid grid-cols-3 gap-3">
            {[['路由器条目', recResult.router], ['补记', recResult.added], ['移除', recResult.removed]].map(([k, v]) => (
              <div key={k as string} className="rounded-ctrl bg-[var(--hover)] px-4 py-3 text-center">
                <div className="mono text-[20px] font-bold">{v}</div>
                <div className="text-[11px] text-t3 mt-0.5">{k}</div>
              </div>
            ))}
          </div>
        )}
        <button onClick={() => setConfirmRec(true)} className="btn">
          <RefreshCw size={14} /> 执行对账
        </button>
      </div>

      {/* 视觉效果 */}
      <div className="card p-6 space-y-3">
        <div style={{ fontSize: 13.5, fontWeight: 600 }}>视觉效果</div>
        <p className="text-sm text-3">完整模式包含环境光斑与玻璃模糊；低性能设备可选精简。</p>
        <Switch checked={fx === 'full'} onChange={v => setFx(v ? 'full' : 'off')}
          label={fx === 'full' ? '完整' : '精简'} />
      </div>

      <ConfirmModal open={!!confirmDel} danger confirmLabel="确认删除"
        title={`删除设备「${confirmDel?.name}」？`}
        desc={confirmDel && devices.find(d => d.id === confirmDel.id)?.is_default
          ? '这是当前默认设备，删除后系统会自动把第一台设备设为默认。'
          : '删除后需要重新绑定才能继续使用该设备的监控与封禁功能。'}
        onClose={() => setConfirmDel(null)}
        onConfirm={() => confirmDel && del(confirmDel.id, confirmDel.name)} />
      <ConfirmModal open={confirmRec} confirmLabel="开始对账"
        title="执行防火墙对账？"
        desc="将读取路由器当前封禁列表并同步到面板数据库，不会改动路由器规则。"
        onClose={() => setConfirmRec(false)} onConfirm={reconcile} />

      {(showAdd || editing) && (
        <DeviceModal
          device={editing}
          onClose={() => { setShowAdd(false); setEditing(null) }}
          onSaved={() => { setShowAdd(false); setEditing(null); setMsg('已保存'); load() }}
        />
      )}
    </div>
  )
}

function DeviceModal({ device, onClose, onSaved }: { device: any, onClose: () => void, onSaved: () => void }) {
  const [form, setForm] = useState({
    name: device?.name ?? '', host: device?.host ?? '192.168.8.1',
    port: device?.port ?? 443, username: device?.username ?? 'panel',
    password: '', auth_method: device?.auth_method ?? 'rest',
    verify_tls: device?.verify_tls ?? false, timeout: device?.timeout ?? 10,
  })
  const [msg, setMsg] = useState('')
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)

  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }))
  const switchAuth = (m: string) => { set('auth_method', m); set('port', m === 'ssh' ? 22 : 443) }

  const test = async () => {
    setMsg(''); setTesting(true)
    try {
      const { data } = await api.post('/wizard/test-connection', form)
      setMsg(data.message)
    } catch (e: any) { setMsg(e.response?.data?.detail || '请求失败') }
    finally { setTesting(false) }
  }

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      if (device) {
        await api.put(`/wizard/devices/${device.id}`, form)
      } else {
        await api.post('/wizard/bind', { ...form, name: form.name || '新设备' })
      }
      onSaved()
    } catch (e: any) { setMsg(e.response?.data?.detail || '保存失败') }
    finally { setSaving(false) }
  }

  return (
    <Modal open onClose={onClose} title={device ? '编辑设备' : '添加设备'} width={460}>
      <div className="space-y-4">
        {[['name', '设备名称'], ['host', '路由器 IP'], ['username', '用户名'], ['password', device ? '新密码（留空不修改）' : '密码']].map(([k, label]) => (
          <input key={k} className="input" style={{ padding: '10px 12px' }}
            type={k === 'password' ? 'password' : 'text'}
            placeholder={label}
            aria-label={label}
            value={form[k as keyof typeof form]}
            onChange={e => set(k, e.target.value)} />
        ))}
        <div className="flex gap-3">
          <select className="input" style={{ padding: '10px 12px', flex: 1 }} value={form.auth_method}
            onChange={e => switchAuth(e.target.value)}>
            <option value="rest">REST API</option>
            <option value="ssh">SSH</option>
          </select>
          <input className="input" style={{ padding: '10px 12px', width: 96 }} type="number" placeholder="端口"
            value={form.port} onChange={e => set('port', +e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm text-2">
          <input type="checkbox" checked={form.verify_tls} onChange={e => set('verify_tls', e.target.checked)} className="rounded" />
          校验 HTTPS 证书（自签证书请勿勾选）
        </label>
        {msg && <div className="text-sm text-2 rounded-xl py-2 px-4" style={{ background: 'var(--hover)' }}>{msg}</div>}
        <div className="flex gap-3">
          <button disabled={testing} onClick={test} className="btn flex-1" style={{ padding: '10px 0' }}>{testing ? '测试中…' : '测试连接'}</button>
          <button disabled={saving} onClick={save} className="flex-1 h-10 rounded-ctrl text-[13px] font-semibold text-black cursor-pointer hover:opacity-90 disabled:opacity-40" style={{ background: 'var(--signal)' }}>{saving ? '保存中…' : '保存'}</button>
        </div>
        <button onClick={onClose} className="w-full text-sm text-3 hover:text-t2 cursor-pointer">取消</button>
      </div>
    </Modal>
  )
}



