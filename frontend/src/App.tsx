import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './views/Login'
import Wizard from './views/Wizard'
import Dashboard from './views/Dashboard'
import DevicesPage from './views/DevicesPage'
import NetworkPage from './views/NetworkPage'
import Settings from './views/Settings'
import Layout from './components/shell/Layout'
import { api } from './api/client'

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!localStorage.getItem('access_token')) return <Navigate to="/login" replace />
  return <>{children}</>
}

function RequireBound({ children }: { children: React.ReactNode }) {
  const [bound, setBound] = useState<boolean | null>(null)
  const [skipped] = useState(() => sessionStorage.getItem('rp-bind-skipped') === '1')
  useEffect(() => {
    if (skipped) { setBound(true); return }
    api.get('/wizard/devices')
      .then(r => setBound((r.data?.length ?? 0) > 0))
      .catch(() => setBound(false))
  }, [skipped])
  if (bound === null) return <div className="min-h-screen flex items-center justify-center text-t3 text-sm">加载中…</div>
  if (!bound) return <Navigate to="/wizard" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/wizard" element={<RequireAuth><Wizard /></RequireAuth>} />
      <Route element={<RequireAuth><RequireBound><Layout /></RequireBound></RequireAuth>}>
        <Route path="/" element={<Dashboard />} />
        {/* 终端下的二级页面：设备列表 / 封禁列表 */}
        <Route path="/devices" element={<DevicesPage tab="devices" />} />
        <Route path="/devices/blocked" element={<DevicesPage tab="blocked" />} />
        <Route path="/blocked" element={<Navigate to="/devices/blocked" replace />} />
        <Route path="/network" element={<NetworkPage />} />
        <Route path="/network/:tab" element={<NetworkPage />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
