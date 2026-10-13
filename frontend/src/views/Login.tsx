/**
 * 登录页：参考 Sun-Panel —— 彩色光斑背景 + 居中单卡片。
 * 无 slogan、无装饰性大图形；文案为英文，标签清晰。
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { User, Lock, Sun, Moon, Wand2 } from 'lucide-react'
import api from '../api/client'
import { Logo } from '../components/ui/Logo'
import { BlobField } from '../components/shell/BlobField'
import { useUi } from '../lib/store'

export default function Login() {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const nav = useNavigate()
  const { theme, toggleTheme, fx, setFx } = useUi()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setErr('')
    try {
      const { data } = await api.post('/auth/login', { username, password })
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      nav('/')
    } catch (e: any) {
      setErr(e.response?.data?.detail || 'Login failed')
    } finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen relative flex items-center justify-center p-6 overflow-hidden">
      {/* 背景光斑（参考图的彩色散景） */}
      <BlobField
        className="absolute inset-0"
        strong
        blobs={[
          { x: 8, y: 2, size: 620, tone: 'violet' },
          { x: 20, y: 30, size: 760, tone: 'blue' },
          { x: 30, y: 68, size: 460, tone: 'cyan' },
          { x: 62, y: -6, size: 820, tone: 'blue' },
          { x: 66, y: 58, size: 700, tone: 'violet' },
          { x: 84, y: 26, size: 380, tone: 'cyan' },
        ]}
      />
      <div className="noise" />

      {/* 居中卡片 */}
      <form onSubmit={submit} className="relative z-10 w-full max-w-[400px] rounded-[16px] border p-7"
        style={{ background: 'var(--login-card)', borderColor: 'var(--border-strong)', boxShadow: 'var(--shadow-float)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}>

        {/* 顶部两个小控件 */}
        <div className="flex items-center justify-between mb-6">
          <button type="button" onClick={toggleTheme} aria-label={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}
            className="w-8 h-8 rounded-full flex items-center justify-center cursor-pointer transition-colors"
            style={{ background: 'var(--hover)', color: 'var(--text-2)' }}>
            {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <button type="button" onClick={() => setFx(fx === 'full' ? 'off' : 'full')}
            aria-label="visual effects" title={fx === 'full' ? 'Effects: full' : 'Effects: minimal'}
            className="h-8 px-3 rounded-ctrl flex items-center gap-1.5 cursor-pointer text-[12px] transition-colors"
            style={{ border: '1px solid var(--border-strong)', color: 'var(--text-2)' }}>
            <Wand2 size={13} />
            {fx === 'full' ? 'Effects' : 'Minimal'}
          </button>
        </div>

        {/* 品牌 */}
        <div className="flex flex-col items-center mb-7">
          <span style={{ color: 'var(--signal)' }}><Logo size={44} /></span>
          <div className="mt-3 text-[26px] font-bold tracking-tight">RPanel</div>
        </div>

        {err && (
          <div className="mb-4 rounded-ctrl px-3.5 py-2.5 text-[13px]"
            style={{ border: '1px solid var(--danger)', color: 'var(--danger)', background: 'var(--danger-dim)' }}>
            {err}
          </div>
        )}

        {/* 输入 */}
        <div className="space-y-4">
          <div className="relative">
            <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: 'var(--text-3)' }} />
            <input value={username} onChange={e => setUsername(e.target.value)} placeholder="Username" aria-label="Username"
              autoComplete="username" className="login-input" />
          </div>
          <div className="relative">
            <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: 'var(--text-3)' }} />
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Password" aria-label="Password"
              autoComplete="current-password" className="login-input" />
          </div>
        </div>

        <button type="submit" disabled={loading}
          className="mt-6 w-full h-10 rounded-ctrl text-[14px] font-semibold cursor-pointer transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ background: 'var(--signal)', color: '#0A0D08' }}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>

        <div className="mt-5 flex flex-col items-center gap-1">
          <div className="text-[11.5px]" style={{ color: 'var(--text-3)' }}>RPanel</div>
          <a href="https://github.com/Zhengbf/rpanel" target="_blank" rel="noopener noreferrer"
            className="text-[10.5px] hover:underline" style={{ color: 'var(--text-3)' }}>by bf</a>
        </div>
      </form>
    </div>
  )
}
