import { useEffect, useState } from 'react'
import { X, UserPlus } from 'lucide-react'
import api from '../api/client'
import { useWebSocket } from '../ws/useWebSocket'

/** 全局新设备告警条：WebSocket alerts 主题 + 未确认列表 */
export default function AlertBar() {
  const [alerts, setAlerts] = useState<any[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  useWebSocket(['alerts'], (_t, data) => {
    if (data?.new_devices) setAlerts(prev => {
      const seen = new Set(prev.map(p => p.mac))
      return [...prev, ...data.new_devices.filter((n: any) => !seen.has(n.mac))]
    })
  })

  useEffect(() => {
    api.get('/alerts/new-devices').then(r => setAlerts(r.data)).catch(() => {})
  }, [])

  const ack = async () => {
    await api.post('/alerts/ack').catch(() => {})
    setAlerts([]); setDismissed(new Set())
  }

  const visible = alerts.filter(a => !dismissed.has(a.mac))
  if (!visible.length) return null

  return (
    <div className="glass-l2 animate-in" style={{
      marginBottom: 16, padding: '12px 16px', borderRadius: 14,
      display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
    }}>
      <UserPlus size={15} className="text-red" />
      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--red)' }}>
        发现 {visible.length} 台新设备：
      </span>
      {visible.slice(0, 5).map(a => (
        <span key={a.mac} className="mono" style={{ fontSize: 12, color: 'var(--text-2)' }}>
          {a.hostname || a.mac.slice(0, 8)} ({a.ip})
        </span>
      ))}
      {visible.length > 5 && <span className="text-3" style={{ fontSize: 12 }}>等 {visible.length} 台</span>}
      <button className="h-8 px-3 rounded-ctrl border border-[var(--border)] text-[12.5px] text-t2 hover:text-t1 hover:bg-[var(--hover)] cursor-pointer" style={{ marginLeft: 'auto' }} onClick={ack}>
        <X size={12} style={{ verticalAlign: -2, marginRight: 4 }} />我知道了
      </button>
    </div>
  )
}
