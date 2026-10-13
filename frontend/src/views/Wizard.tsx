import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'

export default function Wizard() {
  const [form, setForm] = useState({
    name: '主路由', host: '192.168.88.1', port: 443,
    username: 'panel', password: '', auth_method: 'rest',
    verify_tls: false, timeout: 10,
  })
  const [result, setResult] = useState<any>(null)
  const [msg, setMsg] = useState('')
  const [testing, setTesting] = useState(false)
  const [binding, setBinding] = useState(false)
  const nav = useNavigate()
  useEffect(() => {
    if (!localStorage.getItem('access_token')) nav('/login', { replace: true })
  }, [nav])

  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }))
  const switchAuth = (method: string) => {
    set('auth_method', method)
    set('port', method === 'ssh' ? 22 : 443)
  }

  const test = async () => {
    setMsg(''); setResult(null); setTesting(true)
    try {
      const { data } = await api.post('/wizard/test-connection', form)
      setResult(data); setMsg(data.message)
    } catch (e: any) { setMsg(e.response?.data?.detail || '请求失败') }
    finally { setTesting(false) }
  }

  const bind = async () => {
    setMsg(''); setBinding(true)
    try {
      await api.post('/wizard/bind', form)
      nav('/')
    } catch (e: any) { setMsg(e.response?.data?.detail || '绑定失败') }
    finally { setBinding(false) }
  }

  const skip = () => {
    sessionStorage.setItem('rp-bind-skipped', '1')
    nav('/', { replace: true })
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10">
      <div className="glass-l2 animate-in p-6 sm:p-10 w-full max-w-lg space-y-5">
        <div className="space-y-1 mb-2">
          <h1 className="page-title">绑定 RouterOS 设备</h1>
          <p className="text-sm text-3">支持多台设备，随时可在设置中管理</p>
        </div>
        {['name', 'host', 'username', 'password'].map(k => (
          <input key={k} className="input" style={{ padding: '10px 12px' }}
            type={k === 'password' ? 'password' : 'text'}
            placeholder={k === 'name' ? '设备名称' : k === 'host' ? '路由器 IP（如 192.168.88.1）' : k === 'username' ? '用户名' : '密码'}
            value={String(form[k as 'name' | 'host' | 'username' | 'password'] ?? '')}
            onChange={e => set(k, e.target.value)} />
        ))}
        <div className="flex items-center gap-3">
          <select className="input" style={{ padding: '10px 12px', flex: 1 }}
            value={form.auth_method} onChange={e => switchAuth(e.target.value)}>
            <option value="rest">REST API（推荐）</option>
            <option value="ssh">SSH</option>
          </select>
          <input className="input" style={{ padding: '10px 12px', width: 96 }} type="number"
            placeholder="端口" value={form.port}
            onChange={e => set('port', +e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm text-2">
          <input type="checkbox" checked={form.verify_tls}
            onChange={e => set('verify_tls', e.target.checked)} className="rounded" />
          校验 HTTPS 证书（自签证书请勿勾选）
        </label>
        {msg && <div className="rounded-ctrl py-2.5 px-4 text-[13px]"
            style={result?.ok
              ? { background: 'var(--signal-dim)', color: 'var(--signal)' }
              : { background: 'var(--danger-dim)', color: 'var(--danger)' }}>{msg}</div>}
        {result?.ok && <div className="rounded-ctrl py-2.5 px-4 text-[13px] mono" style={{ background: 'var(--signal-dim)', color: 'var(--signal)' }}>RouterOS {result.routeros_version} · {result.identity}</div>}
        <div className="flex gap-3">
          <button disabled={testing} onClick={test} className="btn flex-1" style={{ padding: '10px 0' }} data-x=" disabled:opacity-50">{testing ? '测试中…' : '测试连接'}</button>
          <button disabled={binding} onClick={bind} className="btn-primary flex-1 py-3 text-sm font-medium text-white disabled:opacity-50">{binding ? '绑定中…' : '绑定'}</button>
        </div>
        <button onClick={skip} className="w-full text-sm text-3">跳过，稍后再绑定</button>
      </div>
    </div>
  )
}

